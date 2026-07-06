using System;
using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeProceduralAgentAnimator : MonoBehaviour
    {
        [SerializeField] private string agentId;
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private Transform bodyRoot;
        [SerializeField] private Transform head;
        [SerializeField] private Transform leftUpperArm;
        [SerializeField] private Transform rightUpperArm;
        [SerializeField] private Transform leftForearm;
        [SerializeField] private Transform rightForearm;
        [SerializeField] private Transform leftHandProp;
        [SerializeField] private Transform rightHandProp;
        [SerializeField] private Transform scanBeam;
        [SerializeField] private Transform activityLight;
        [SerializeField] private float motionScale = 1.0f;

        private string activeAction = "idle";
        private float actionStartedAt;
        private Vector3 bodyBasePosition;
        private Vector3 activityLightBaseScale;
        private Quaternion headBaseRotation;
        private Quaternion leftUpperBaseRotation;
        private Quaternion rightUpperBaseRotation;
        private Quaternion leftForearmBaseRotation;
        private Quaternion rightForearmBaseRotation;
        private bool basePoseCached;

        private void Awake()
        {
            CacheBasePose();
        }

        public void PreviewAction(string actionTemplateId, float elapsed)
        {
            CacheBasePose();
            activeAction = string.IsNullOrWhiteSpace(actionTemplateId) ? "idle" : actionTemplateId;
            ApplyPose(elapsed);
        }

        private void CacheBasePose()
        {
            if (basePoseCached)
            {
                return;
            }

            if (bodyRoot == null)
            {
                bodyRoot = transform;
            }

            bodyBasePosition = bodyRoot.localPosition;
            activityLightBaseScale = activityLight != null ? activityLight.localScale : Vector3.one;
            headBaseRotation = head != null ? head.localRotation : Quaternion.identity;
            leftUpperBaseRotation = leftUpperArm != null ? leftUpperArm.localRotation : Quaternion.identity;
            rightUpperBaseRotation = rightUpperArm != null ? rightUpperArm.localRotation : Quaternion.identity;
            leftForearmBaseRotation = leftForearm != null ? leftForearm.localRotation : Quaternion.identity;
            rightForearmBaseRotation = rightForearm != null ? rightForearm.localRotation : Quaternion.identity;
            basePoseCached = true;
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

        private void Update()
        {
            CacheBasePose();
            ApplyPose(Time.time - actionStartedAt);
        }

        private void ApplyPose(float t)
        {
            var pulse = Mathf.Sin(t * 5.5f) * motionScale;
            var slow = Mathf.Sin(t * 1.7f) * motionScale;

            bodyRoot.localPosition = bodyBasePosition + new Vector3(0, Mathf.Abs(slow) * 0.012f, 0);
            bodyRoot.localRotation = Quaternion.identity;
            SetRotation(head, headBaseRotation, new Vector3(slow * 2.0f, pulse * 3.0f, 0));
            SetRotation(leftUpperArm, leftUpperBaseRotation, Vector3.zero);
            SetRotation(rightUpperArm, rightUpperBaseRotation, Vector3.zero);
            SetRotation(leftForearm, leftForearmBaseRotation, Vector3.zero);
            SetRotation(rightForearm, rightForearmBaseRotation, Vector3.zero);
            SetActive(leftHandProp, false);
            SetActive(rightHandProp, false);
            SetActive(scanBeam, false);
            Pulse(activityLight, 1.0f);

            if (IsAction("coffee"))
            {
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(54 + pulse * 3, -16, -10));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-74 + pulse * 5, 0, 0));
                SetRotation(leftUpperArm, leftUpperBaseRotation, new Vector3(16, 0, 8));
                SetActive(rightHandProp, true);
            }
            else if (IsAction("cook"))
            {
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(44 + pulse * 12, -22, 8));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-52 + pulse * 18, 0, 0));
                SetRotation(leftUpperArm, leftUpperBaseRotation, new Vector3(36 - pulse * 6, 18, -6));
                SetRotation(leftForearm, leftForearmBaseRotation, new Vector3(-38, 0, 0));
                bodyRoot.localRotation = Quaternion.Euler(0, slow * 5, 0);
                SetActive(rightHandProp, true);
            }
            else if (IsAction("sketch") || IsAction("desk"))
            {
                SetRotation(head, headBaseRotation, new Vector3(14 + slow * 2, 0, 0));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(48, -8, -8 + pulse * 5));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-62 + pulse * 8, 0, 0));
                SetRotation(leftUpperArm, leftUpperBaseRotation, new Vector3(28, 8, 10));
                SetRotation(leftForearm, leftForearmBaseRotation, new Vector3(-35, 0, 0));
                SetActive(rightHandProp, true);
            }
            else if (IsAction("scan"))
            {
                SetRotation(head, headBaseRotation, new Vector3(-3, pulse * 9, 0));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(25, -20 + pulse * 5, -4));
                SetActive(scanBeam, true);
                Pulse(activityLight, 1.0f + Mathf.Abs(pulse) * 0.12f);
            }
            else if (IsAction("repair"))
            {
                bodyRoot.localPosition = bodyBasePosition + new Vector3(0, -0.045f + Mathf.Abs(pulse) * 0.01f, 0);
                SetRotation(head, headBaseRotation, new Vector3(18, pulse * 2, 0));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(58 + pulse * 8, -12, 2));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-72 + pulse * 14, 0, 0));
                SetActive(rightHandProp, true);
                Pulse(activityLight, 1.0f + Mathf.Abs(pulse) * 0.10f);
            }
            else if (IsAction("call"))
            {
                SetRotation(head, headBaseRotation, new Vector3(0, 0, -8 + slow * 2));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(76, -34, -16));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-98, 0, 0));
                SetActive(rightHandProp, true);
            }
            else if (IsAction("dance"))
            {
                bodyRoot.localPosition = bodyBasePosition + new Vector3(Mathf.Sin(t * 3.2f) * 0.045f, Mathf.Abs(pulse) * 0.035f, 0);
                bodyRoot.localRotation = Quaternion.Euler(0, slow * 10, pulse * 2);
                SetRotation(leftUpperArm, leftUpperBaseRotation, new Vector3(68 + pulse * 12, 0, 24));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(68 - pulse * 12, 0, -24));
                SetRotation(leftForearm, leftForearmBaseRotation, new Vector3(-58, 0, 0));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-58, 0, 0));
                Pulse(activityLight, 1.0f + Mathf.Abs(pulse) * 0.08f);
            }
            else if (IsAction("talk"))
            {
                SetRotation(head, headBaseRotation, new Vector3(slow * 2, pulse * 3, 0));
                SetRotation(rightUpperArm, rightUpperBaseRotation, new Vector3(26 + pulse * 5, -12, -10));
                SetRotation(rightForearm, rightForearmBaseRotation, new Vector3(-32 + pulse * 7, 0, 0));
            }
            else if (IsAction("charge"))
            {
                Pulse(activityLight, 1.0f + Mathf.Abs(slow) * 0.18f);
            }
            else
            {
                bodyRoot.localRotation = Quaternion.Slerp(bodyRoot.localRotation, Quaternion.identity, Time.deltaTime * 8.0f);
            }
        }

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent == null || behaviorEvent.agentId != agentId)
            {
                return;
            }

            activeAction = string.IsNullOrWhiteSpace(behaviorEvent.actionTemplateId) ? "idle" : behaviorEvent.actionTemplateId;
            actionStartedAt = Time.time;
        }

        private bool IsAction(string action)
        {
            return string.Equals(activeAction, action, StringComparison.OrdinalIgnoreCase);
        }

        private static void SetRotation(Transform target, Quaternion baseRotation, Vector3 localEulerOffset)
        {
            if (target == null)
            {
                return;
            }

            target.localRotation = baseRotation * Quaternion.Euler(localEulerOffset);
        }

        private static void SetActive(Transform target, bool active)
        {
            if (target != null && target.gameObject.activeSelf != active)
            {
                target.gameObject.SetActive(active);
            }
        }

        private void Pulse(Transform target, float scale)
        {
            if (target != null)
            {
                target.localScale = activityLightBaseScale * scale;
            }
        }
    }
}
