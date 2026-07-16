using System;
using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// Game-world perception input: converts DETERMINISTIC Unity object state
    /// into structured perception events for the Character Runtime — no
    /// screenshots, no VLM guessing. Attach watched objects; when one enters
    /// or leaves the sensing radius the reporter emits an object/person event
    /// through the SoulForgeProtocolClient's socket as a wire Event frame.
    ///
    /// The component is fail-closed: perceptionEnabled defaults to false and
    /// must be enabled explicitly by scene configuration or trusted UI code.
    /// </summary>
    public class SoulForgePerceptionReporter : MonoBehaviour
    {
        [Serializable]
        public class WatchedObject
        {
            public Transform target;
            public string label = "object";     // person / cup / door ...
            [NonSerialized] public bool wasInRange;
        }

        [Header("Opt-in")]
        [Tooltip("Default off. Enable explicitly to publish structured scene perception events.")]
        [SerializeField] private bool perceptionEnabled = false;

        [Header("Scene inputs")]
        [SerializeField] private SoulForgeProtocolClient client;
        [SerializeField] private Transform sensingOrigin;
        [Min(0f)]
        [SerializeField] private float sensingRadius = 4f;
        [SerializeField] private string targetAgent = "kai";
        [SerializeField] private List<WatchedObject> watched = new();

        public bool PerceptionEnabled => perceptionEnabled;

        [Serializable]
        private class WireEventMsg
        {
            public string type = "event";
            public string kind;
            public string source = "unity-scene";
            public string text;
            public string target_agent;
        }

        private void Update()
        {
            if (!perceptionEnabled || client == null || !client.IsConnected || sensingOrigin == null) return;
            foreach (var item in watched)
            {
                if (item == null || item.target == null) continue;
                bool inRange = Vector3.Distance(sensingOrigin.position,
                                                item.target.position) <= sensingRadius;
                if (inRange == item.wasInRange) continue;
                item.wasInRange = inRange;
                if (!inRange) continue;         // v0: report appearances only

                var msg = new WireEventMsg
                {
                    kind = item.label == "person" ? "person_detected" : "object_detected",
                    text = item.label + " detected",
                    target_agent = targetAgent,
                };
                client.EnqueueOutbound(JsonUtility.ToJson(msg));
            }
        }

        /// <summary>
        /// Explicit opt-in/out entry point for a trusted settings UI. Disabling
        /// resets edge state so a later opt-in gets a fresh scene snapshot.
        /// </summary>
        public void SetPerceptionEnabled(bool enabled)
        {
            if (perceptionEnabled == enabled) return;
            perceptionEnabled = enabled;
            ResetRangeState();
        }

        private void OnDisable()
        {
            ResetRangeState();
        }

        private void OnValidate()
        {
            sensingRadius = Mathf.Max(0f, sensingRadius);
        }

        private void ResetRangeState()
        {
            if (watched == null) return;
            foreach (var item in watched)
            {
                if (item != null) item.wasInRange = false;
            }
        }
    }
}
