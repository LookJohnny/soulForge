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

            // humanoid avatars keep their real facing pointed at the camera;
            // added at runtime so existing scenes need no rewiring
            if (animator != null && animator.avatar != null && animator.avatar.isHuman
                && GetComponent<SoulForgeFacingCorrector>() == null)
            {
                gameObject.AddComponent<SoulForgeFacingCorrector>();
            }
            if (animator != null && animator.avatar != null && animator.avatar.isHuman
                && GetComponent<SoulForgeHologramLook>() == null)
            {
                gameObject.AddComponent<SoulForgeHologramLook>();
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

            // the Joi move: approach_user glides the character to a spot just
            // in front of the camera — where the "user" stands in this scene
            if (behaviorEvent.actionTemplateId != null
                && behaviorEvent.actionTemplateId.Contains("approach_user")
                && Camera.main != null)
            {
                var cameraTransform = Camera.main.transform;
                var forward = cameraTransform.forward;
                forward.y = 0f;
                if (forward.sqrMagnitude > 0.001f)
                {
                    var spot = cameraTransform.position + forward.normalized * 1.4f;
                    spot.y = 0f;
                    desiredPosition = spot;
                    hasDesiredPosition = true;
                }
            }

            if (SoulForgeAgentRegistry.TryGetAgent(behaviorEvent.lookAtAgentId, out var target))
            {
                lookAtTarget = target;
            }

            // triggers/params only make sense on an Animator that is actually
            // playing a controller — a VRM avatar driven by the mocap idle (or
            // nothing) has no such parameters, and calling anyway floods the
            // console with "Animator is not playing an AnimatorController"
            var hasController = animator != null && animator.runtimeAnimatorController != null;
            if (hasController && !string.IsNullOrWhiteSpace(behaviorEvent.actionTemplateId)
                && HasParameter(behaviorEvent.actionTemplateId))
            {
                if (HasParameter("idle")) animator.ResetTrigger("idle");
                animator.SetTrigger(behaviorEvent.actionTemplateId);
            }

            if (hasController && !string.IsNullOrWhiteSpace(behaviorEvent.emotion)
                && HasParameter("emotion"))
            {
                animator.SetFloat("emotion", EmotionToFloat(behaviorEvent.emotion));
            }
        }

        private bool HasParameter(string name)
        {
            foreach (var parameter in animator.parameters)
            {
                if (parameter.name == name)
                {
                    return true;
                }
            }
            return false;
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
