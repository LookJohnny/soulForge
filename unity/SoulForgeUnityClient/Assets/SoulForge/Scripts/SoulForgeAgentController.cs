using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeAgentController : MonoBehaviour
    {
        [SerializeField] private string agentId;
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private Animator animator;
        [SerializeField] private SoulForgeProceduralAgentAnimator proceduralAnimator;
        [SerializeField] private AudioSource audioSource;
        [SerializeField] private float moveLerp = 3.5f;
        [SerializeField] private Transform lookAtTarget;

        private Vector3 desiredPosition;
        private bool hasDesiredPosition;

        private void Reset()
        {
            animator = GetComponentInChildren<Animator>();
            proceduralAnimator = GetComponentInChildren<SoulForgeProceduralAgentAnimator>();
            audioSource = GetComponentInChildren<AudioSource>();
        }

        private void OnEnable()
        {
            SoulForgeAgentRegistry.Register(agentId, transform);

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

            SoulForgeAgentRegistry.Unregister(agentId, transform);
        }

        private void Update()
        {
            if (hasDesiredPosition)
            {
                transform.position = Vector3.Lerp(transform.position, desiredPosition, Time.deltaTime * moveLerp);
            }

            if (lookAtTarget != null)
            {
                var direction = lookAtTarget.position - transform.position;
                direction.y = 0;
                if (direction.sqrMagnitude > 0.001f)
                {
                    transform.rotation = Quaternion.Slerp(transform.rotation, Quaternion.LookRotation(direction), Time.deltaTime * 4.0f);
                }
            }
        }

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent.agentId != agentId)
            {
                return;
            }

            if (behaviorEvent.targetPosition != null)
            {
                desiredPosition = behaviorEvent.targetPosition.ToUnityVector3();
                hasDesiredPosition = true;
            }

            if (SoulForgeAgentRegistry.TryGetAgent(behaviorEvent.lookAtAgentId, out var target))
            {
                lookAtTarget = target;
            }

            if (animator != null && !string.IsNullOrWhiteSpace(behaviorEvent.actionTemplateId))
            {
                animator.ResetTrigger("idle");
                animator.SetTrigger(behaviorEvent.actionTemplateId);
            }

            if (animator != null && !string.IsNullOrWhiteSpace(behaviorEvent.emotion))
            {
                animator.SetFloat("emotion", EmotionToFloat(behaviorEvent.emotion));
            }
        }

        private static float EmotionToFloat(string emotion)
        {
            if (emotion == "happy")
            {
                return 1.0f;
            }

            if (emotion == "excited")
            {
                return 0.9f;
            }

            if (emotion == "warm")
            {
                return 0.7f;
            }

            if (emotion == "calm")
            {
                return 0.45f;
            }

            if (emotion == "robot")
            {
                return 0.25f;
            }

            return 0.5f;
        }
    }
}
