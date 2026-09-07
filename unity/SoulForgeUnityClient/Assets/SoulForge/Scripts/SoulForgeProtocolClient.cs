using System;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// SoulForge Protocol 0.2 body client.
    ///
    /// Connects to the Runtime Server's /body endpoint, registers with a
    /// BodyHello + EmbodimentManifest, receives canonical ActionCommands and
    /// executes them on the Unity main thread by translating them into the
    /// existing SoulForgeBehaviorEvent pipeline (Bridge → AgentControllers →
    /// Animator / procedural animation / dialogue HUD / voice).
    ///
    /// Responsibilities honored here:
    ///  - main-thread execution (network task only enqueues)
    ///  - Observation (done/failed/rejected) after each action
    ///  - reconnect with backoff + re-hello + per-agent sequence dedupe
    ///  - one Unity scene may host several characters (agentIds list),
    ///    and the same character may simultaneously live in other bodies —
    ///    identity/memory stay server-side, this component holds no soul state.
    ///
    /// The Character Runtime never drives Update/physics/NavMesh — that stays
    /// in Unity. NOTE: compiled on the bench, not in CI — see docs.
    /// </summary>
    public class SoulForgeProtocolClient : MonoBehaviour
    {
        [Header("Server")]
        [SerializeField] private string serverUrl = "ws://127.0.0.1:8765/body";
        [SerializeField] private string bodyId = "unity-apartment-1";
        [SerializeField] private string[] agentIds = { "luna", "kai", "pipo" };

        [Header("Scene wiring")]
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private SoulForgeDialogueHud dialogueHud;

        [Header("Reconnect")]
        [SerializeField] private float reconnectInitialDelay = 1f;
        [SerializeField] private float reconnectMaxDelay = 15f;

        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;
        private readonly ConcurrentQueue<ActionCommandMsg> inboundActions = new();
        private readonly ConcurrentQueue<string> outboundFrames = new();
        private readonly Dictionary<string, int> lastSequencePerAgent = new();
        private readonly List<PendingCompletion> pending = new();
        // ACE-style beat sequencing: steps born from one decision share a
        // correlation_id and must play one after another for their duration —
        // last-writer-wins made a wave invisible under its own speak/resume.
        private readonly Dictionary<string, Queue<ActionCommandMsg>> beatQueues = new();
        private readonly Dictionary<string, float> beatBusyUntil = new();
        private volatile bool connected;
        private float lastTickSimMinute;

        private struct PendingCompletion
        {
            public ActionCommandMsg command;
            public float completeAt;   // Time.time
        }

        private void OnEnable()
        {
            cancellation = new CancellationTokenSource();
            _ = NetworkLoop(cancellation.Token);
        }

        private void OnDisable()
        {
            cancellation?.Cancel();
            socket?.Dispose();
            connected = false;
        }

        // ------------------------------------------------------------ network
        private async Task NetworkLoop(CancellationToken token)
        {
            float delay = reconnectInitialDelay;
            while (!token.IsCancellationRequested)
            {
                try
                {
                    socket = new ClientWebSocket();
                    await socket.ConnectAsync(new Uri(serverUrl), token);
                    await SendHello(token);
                    connected = true;
                    delay = reconnectInitialDelay;              // reset backoff
                    await ReceiveLoop(token);
                }
                catch (OperationCanceledException) { return; }
                catch (Exception e)
                {
                    Debug.LogWarning($"[SoulForge] connection lost: {e.Message}");
                }
                connected = false;
                await Task.Delay(TimeSpan.FromSeconds(delay), token).ContinueWith(_ => { });
                delay = Mathf.Min(delay * 2f, reconnectMaxDelay);
            }
        }

        /// <summary>
        /// What this scene can visibly perform. Universal steps are always
        /// accepted on top of this; gestures here surface in the server's
        /// action catalog so the decision model may request them, and the
        /// procedural animator has a pose branch for each gesture.
        /// </summary>
        private static readonly string[] SupportedSteps =
        {
            // speech / attention
            "speak_line", "look_at_user", "look_at_target", "approach_user",
            "wait_for_response", "listening_nod", "micro_nod", "chatting",
            "invite_user", "walk_to",
            // gestures (catalog-selectable; mocap states or pose branches exist)
            "wave", "greet", "think", "celebrate", "clap", "jump", "stretch", "dance",
            "crouch", "stand_up", "point_at", "flirt", "dance_belly", "blow_kiss",
            "think_pose", "excited", "dance_rumba", "sad_idle", "look_around_big",
            "greeting", "idle_alt",
            // activity pantomime
            "stir_pan", "prep_ingredients", "plate_up", "draw_stroke", "take_note",
            "read_page", "study", "lean_back_review", "sit_desk", "sit_sofa",
            "kneel_inspect", "scan_leaves", "probe_soil", "water_plant",
            "wipe_surface", "pick_item", "place_item", "pack_tools", "test_part",
            "turn_wrench", "cleaning", "adjust_pose", "rest",
        };

        private async Task SendHello(CancellationToken token)
        {
            var hello = new BodyHelloMsg
            {
                body_id = bodyId,
                agent_ids = agentIds,
                manifest = new EmbodimentManifestMsg
                {
                    body_id = bodyId,
                    supported_steps = SupportedSteps,
                },
            };
            await SendRaw(JsonUtility.ToJson(hello), token);
        }

        private async Task ReceiveLoop(CancellationToken token)
        {
            var buffer = new byte[64 * 1024];
            var builder = new StringBuilder();
            while (!token.IsCancellationRequested && socket.State == WebSocketState.Open)
            {
                builder.Clear();
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                    if (result.MessageType == WebSocketMessageType.Close) return;
                    builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                } while (!result.EndOfMessage);

                HandleFrame(builder.ToString());
                await FlushOutbound(token);
            }
        }

        private void HandleFrame(string json)
        {
            ProtocolTypeProbe probe;
            try { probe = JsonUtility.FromJson<ProtocolTypeProbe>(json); }
            catch { return; }                                   // malformed: ignore, never die
            if (probe == null || string.IsNullOrEmpty(probe.type)) return;

            switch (probe.type)
            {
                case "welcome":
                    var welcome = JsonUtility.FromJson<WelcomeMsg>(json);
                    Debug.Log($"[SoulForge] registered as {welcome.body_id}; agents: {string.Join(",", welcome.accepted_agents)}");
                    break;
                case "action":
                    var action = JsonUtility.FromJson<ActionCommandMsg>(json);
                    if (action != null && !string.IsNullOrEmpty(action.command_id))
                        inboundActions.Enqueue(action);
                    break;
                case "tick":
                    var tick = JsonUtility.FromJson<TickMsg>(json);
                    if (tick != null) lastTickSimMinute = tick.sim_minute;
                    break;
                case "plan_state":
                    // available for HUDs; intentionally not required for execution
                    break;
            }
        }

        private async Task FlushOutbound(CancellationToken token)
        {
            while (outboundFrames.TryDequeue(out var frame))
                await SendRaw(frame, token);
        }

        private async Task SendRaw(string json, CancellationToken token)
        {
            var bytes = Encoding.UTF8.GetBytes(json);
            await socket.SendAsync(new ArraySegment<byte>(bytes),
                                   WebSocketMessageType.Text, true, token);
        }

        // ---------------------------------------------------- preset interactions
        // number keys fire preset user events at the focused agent (Tab switches):
        //   1 打招呼   2 挥挥手   3 跳个舞   4 我有点累(陪伴模式)   5 想一想
        private static readonly (KeyCode key, string text)[] Presets =
        {
            (KeyCode.Alpha1, "你好呀，今天过得怎么样？"),
            (KeyCode.Alpha2, "挥挥手"),
            (KeyCode.Alpha3, "跳个舞"),
            (KeyCode.Alpha4, "我今天有点累，什么都不想做。"),
            (KeyCode.Alpha5, "想一想"),
        };
        private int focusedAgent;

        private void HandlePresetKeys()
        {
            if (agentIds.Length == 0) return;
            if (Input.GetKeyDown(KeyCode.Tab))
            {
                focusedAgent = (focusedAgent + 1) % agentIds.Length;
                Debug.Log($"[SoulForge] preset target -> {agentIds[focusedAgent]}");
            }
            foreach (var (key, text) in Presets)
            {
                if (!Input.GetKeyDown(key)) continue;
                var payload = "{\"type\":\"event\",\"kind\":\"user_utterance\",\"source\":\"user\""
                    + $",\"text\":{JsonEscape(text)},\"target_agent\":\"{agentIds[focusedAgent]}\"}}";
                EnqueueOutbound(payload);
                Debug.Log($"[SoulForge] preset -> {agentIds[focusedAgent]}: {text}");
            }
        }

        private static string JsonEscape(string value)
        {
            return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }

        // -------------------------------------------------------- main thread
        private void Update()
        {
            HandlePresetKeys();
            while (inboundActions.TryDequeue(out var action))
                ExecuteOnMainThread(action);
            DrainBeatQueues();

            for (int i = pending.Count - 1; i >= 0; i--)
            {
                if (Time.time >= pending[i].completeAt)
                {
                    SendObservation(pending[i].command, "done", "");
                    pending.RemoveAt(i);
                }
            }
        }

        private void ExecuteOnMainThread(ActionCommandMsg action)
        {
            // sequence dedupe: after a reconnect the server may resend frames
            if (lastSequencePerAgent.TryGetValue(action.agent_id, out var last)
                && action.sequence != 0 && action.sequence <= last)
                return;
            if (action.sequence != 0) lastSequencePerAgent[action.agent_id] = action.sequence;

            if (Array.IndexOf(agentIds, action.agent_id) < 0)
            {
                SendObservation(action, "rejected", "agent not embodied here", "E_AGENT");
                return;
            }

            var isBeat = !string.IsNullOrEmpty(action.correlation_id);
            if (isBeat)
            {
                if (!beatQueues.TryGetValue(action.agent_id, out var queue))
                {
                    beatQueues[action.agent_id] = queue = new Queue<ActionCommandMsg>();
                }
                if (queue.Count >= 8)
                {
                    SendObservation(queue.Dequeue(), "interrupted", "beat queue overflow");
                }
                queue.Enqueue(action);
                return;
            }
            // ambient steps (minute-planner ticks) only show when no beat plays
            if (Time.time < BusyUntil(action.agent_id))
            {
                SendObservation(action, "done", "skipped: beat active");
                return;
            }
            PublishAction(action);
        }

        private float BusyUntil(string agentId)
        {
            return beatBusyUntil.TryGetValue(agentId, out var until) ? until : 0f;
        }

        private void DrainBeatQueues()
        {
            foreach (var pair in beatQueues)
            {
                if (pair.Value.Count == 0 || Time.time < BusyUntil(pair.Key)) continue;
                var next = pair.Value.Dequeue();
                beatBusyUntil[pair.Key] = Time.time + Mathf.Max(0.4f, next.duration_s);
                PublishAction(next);
            }
        }

        private void PublishAction(ActionCommandMsg action)
        {
            try
            {
                var behaviorEvent = new SoulForgeBehaviorEvent
                {
                    time = action.sim_minute,
                    agentId = action.agent_id,
                    agentName = action.agent_id,
                    actionTemplateId = string.IsNullOrEmpty(action.template_id)
                        ? action.name : action.template_id + ":" + action.name,
                    dialogue = action.dialogue,
                    emotion = action.safety_class,
                    lookAtAgentId = action.gaze_target,
                    priority = action.priority.ToString(),
                };
                if (bridge != null) bridge.Publish(behaviorEvent);
                if (dialogueHud != null && !string.IsNullOrEmpty(action.dialogue))
                    dialogueHud.SendMessage("ShowLine", behaviorEvent, SendMessageOptions.DontRequireReceiver);

                pending.Add(new PendingCompletion
                {
                    command = action,
                    completeAt = Time.time + Mathf.Max(0.1f, action.duration_s),
                });
            }
            catch (Exception e)
            {
                SendObservation(action, "failed", e.Message, "E_EXEC");
            }
        }

        private void SendObservation(ActionCommandMsg command, string status,
                                     string detail, string errorCode = null)
        {
            var observation = new ObservationMsg
            {
                command_id = command.command_id,
                agent_id = command.agent_id,
                status = status,
                detail = detail,
                body_id = bodyId,
                started_at = command.sim_minute,
                finished_at = lastTickSimMinute,
                error_code = errorCode,
                recoverable = errorCode != "E_EXEC",
            };
            outboundFrames.Enqueue(JsonUtility.ToJson(observation));
            // flushed on the network task after the next inbound frame; if the
            // link is down the queue survives and drains after re-hello
        }

        public bool IsConnected => connected;

        /// <summary>Queue a raw protocol frame (e.g. a perception Event) for
        /// sending on the network task. Used by SoulForgePerceptionReporter.</summary>
        public void EnqueueOutbound(string json)
        {
            if (!string.IsNullOrEmpty(json)) outboundFrames.Enqueue(json);
        }
    }
}
