using UnityEngine;
using VRM;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// Facial life for a VRM avatar: asymmetric blinking, emotion expressions
    /// mapped from behavior events, and energy-style mouth flaps while a line
    /// is being "spoken". Runs on the VRM 0.x BlendShapeProxy so any VRoid /
    /// VRM avatar works without per-model setup. Body motion stays with
    /// SoulForgeProceduralAgentAnimator; this component only owns the face.
    /// </summary>
    public class SoulForgeVrmPresence : MonoBehaviour
    {
        [SerializeField] private string agentId;
        [SerializeField] private SoulForgeBridge bridge;

        [Header("Blink")]
        [SerializeField] private Vector2 blinkInterval = new Vector2(2.2f, 5.5f);
        [SerializeField] private float blinkCloseSeconds = 0.07f;
        [SerializeField] private float blinkOpenSeconds = 0.16f;

        [Header("Speech mouth")]
        [SerializeField] private float secondsPerChar = 0.14f;
        [SerializeField] private Vector2 speakDuration = new Vector2(1.2f, 6.0f);
        [SerializeField] private float mouthHz = 7.5f;

        [Header("Expression")]
        [SerializeField] private float expressionAttack = 6.0f;
        [SerializeField] private float expressionHoldSeconds = 5.0f;
        [SerializeField] private float expressionRelease = 0.8f;

        private VRMBlendShapeProxy proxy;
        private float nextBlinkAt;
        private float blinkPhaseEnd;
        private bool blinkClosing;
        private float blinkWeight;
        private float speakUntil;

        /// <summary>True while a line is being "spoken" (mouth flapping).</summary>
        public bool IsSpeaking => Time.time < speakUntil;
        private float expressionWeight;
        private float expressionUntil;
        private BlendShapePreset expressionPreset = BlendShapePreset.Neutral;

        private void OnEnable()
        {
            proxy = GetComponentInChildren<VRMBlendShapeProxy>();
            nextBlinkAt = Time.time + Random.Range(blinkInterval.x, blinkInterval.y);
            if (bridge != null) bridge.EventReceived += HandleEvent;
        }

        private void Start()
        {
            // several characters playing the same idle in lockstep read as fake:
            // desync phase and speed per instance
            var animator = GetComponentInChildren<Animator>();
            if (animator != null && animator.runtimeAnimatorController != null)
            {
                animator.speed = Random.Range(0.93f, 1.07f);
                var state = animator.GetCurrentAnimatorStateInfo(0);
                animator.Play(state.fullPathHash, 0, Random.value);
            }
        }

        private void OnDisable()
        {
            if (bridge != null) bridge.EventReceived -= HandleEvent;
        }

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent == null || behaviorEvent.agentId != agentId) return;

            if (!string.IsNullOrEmpty(behaviorEvent.dialogue))
            {
                var seconds = Mathf.Clamp(
                    behaviorEvent.dialogue.Length * secondsPerChar,
                    speakDuration.x, speakDuration.y);
                speakUntil = Time.time + seconds;
            }

            var preset = PresetFor(behaviorEvent.emotion);
            if (preset != BlendShapePreset.Neutral)
            {
                expressionPreset = preset;
                expressionUntil = Time.time + expressionHoldSeconds;
            }
        }

        private static BlendShapePreset PresetFor(string emotion)
        {
            switch ((emotion ?? "").ToLowerInvariant())
            {
                case "warm":
                case "friendly":
                case "happy":
                case "joy":
                    return BlendShapePreset.Joy;
                case "playful":
                case "excited":
                    return BlendShapePreset.Fun;
                case "sad":
                case "sorrow":
                case "down":
                    return BlendShapePreset.Sorrow;
                case "angry":
                case "stern":
                    return BlendShapePreset.Angry;
                default:
                    return BlendShapePreset.Neutral;
            }
        }

        private void LateUpdate()
        {
            if (proxy == null) return;
            var now = Time.time;

            // -- blink: quick close, slower open, then schedule the next one
            if (!blinkClosing && blinkWeight <= 0f && now >= nextBlinkAt)
            {
                blinkClosing = true;
                blinkPhaseEnd = now + blinkCloseSeconds;
            }
            if (blinkClosing)
            {
                blinkWeight = Mathf.Clamp01(1f - (blinkPhaseEnd - now) / blinkCloseSeconds);
                if (now >= blinkPhaseEnd)
                {
                    blinkClosing = false;
                    blinkPhaseEnd = now + blinkOpenSeconds;
                    nextBlinkAt = now + Random.Range(blinkInterval.x, blinkInterval.y);
                }
            }
            else if (blinkWeight > 0f)
            {
                blinkWeight = Mathf.Clamp01((blinkPhaseEnd - now) / blinkOpenSeconds);
            }

            // -- expression: fast attack toward 1 while held, slow release after
            var expressionTarget = now < expressionUntil ? 0.85f : 0f;
            var rate = expressionTarget > expressionWeight ? expressionAttack : expressionRelease;
            expressionWeight = Mathf.MoveTowards(
                expressionWeight, expressionTarget, rate * Time.deltaTime);

            // -- speech: energy-style mouth flaps while the line plays
            float mouth = 0f;
            if (now < speakUntil)
            {
                var pulse = 0.5f + 0.5f * Mathf.Sin(now * mouthHz * Mathf.PI * 2f);
                mouth = 0.12f + 0.55f * pulse;
            }

            proxy.AccumulateValue(BlendShapeKey.CreateFromPreset(BlendShapePreset.Blink), blinkWeight);
            proxy.AccumulateValue(BlendShapeKey.CreateFromPreset(BlendShapePreset.A), mouth);
            if (expressionPreset != BlendShapePreset.Neutral)
            {
                proxy.AccumulateValue(
                    BlendShapeKey.CreateFromPreset(expressionPreset), expressionWeight);
            }
            proxy.Apply();
        }
    }
}
