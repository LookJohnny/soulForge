using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeTimelineDirector : MonoBehaviour
    {
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private Camera targetCamera;
        [SerializeField] private Transform defaultShot;
        [SerializeField] private List<NamedShot> shots = new List<NamedShot>();
        [SerializeField] private float cameraLerp = 2.4f;

        private readonly Dictionary<string, Transform> shotByName = new Dictionary<string, Transform>();
        private Transform activeShot;

        private void Awake()
        {
            if (targetCamera == null)
            {
                targetCamera = Camera.main;
            }

            foreach (var shot in shots)
            {
                if (shot != null && shot.anchor != null && !string.IsNullOrWhiteSpace(shot.name))
                {
                    shotByName[shot.name] = shot.anchor;
                }
            }

            activeShot = defaultShot;
        }

        private void OnEnable()
        {
            if (bridge != null)
            {
                bridge.EventReceived += HandleEvent;
            }
        }

        private void OnDisable()
        {
            if (bridge != null)
            {
                bridge.EventReceived -= HandleEvent;
            }
        }

        private void LateUpdate()
        {
            if (targetCamera == null || activeShot == null)
            {
                return;
            }

            var cameraTransform = targetCamera.transform;
            cameraTransform.position = Vector3.Lerp(cameraTransform.position, activeShot.position, Time.deltaTime * cameraLerp);
            cameraTransform.rotation = Quaternion.Slerp(cameraTransform.rotation, activeShot.rotation, Time.deltaTime * cameraLerp);
        }

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (!string.IsNullOrWhiteSpace(behaviorEvent.cameraShot) && shotByName.TryGetValue(behaviorEvent.cameraShot, out var shot))
            {
                activeShot = shot;
            }
        }
    }

    [System.Serializable]
    public class NamedShot
    {
        public string name;
        public Transform anchor;
    }
}
