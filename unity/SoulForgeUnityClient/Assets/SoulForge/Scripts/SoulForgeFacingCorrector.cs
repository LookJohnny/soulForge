using UnityEngine;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// Keeps a humanoid's TRUE facing gently oriented toward the camera.
    ///
    /// Forward is computed from the animated shoulder line every frame, so it
    /// is immune to import conventions and to whatever root orientation a
    /// mocap clip bakes in — the two things that made yaw guessing fail.
    /// The correction is rate-limited so it reads as a person shifting their
    /// stance, not a turntable.
    /// </summary>
    public class SoulForgeFacingCorrector : MonoBehaviour
    {
        [SerializeField] private float degreesPerSecond = 30f;
        [SerializeField] private float deadZoneDegrees = 12f;

        private Animator animator;
        private Vector3 smoothedForward;

        private void Start()
        {
            animator = GetComponentInChildren<Animator>();
        }

        private void LateUpdate()
        {
            if (animator == null || animator.avatar == null || !animator.avatar.isHuman) return;
            var camera = Camera.main;
            if (camera == null) return;

            var left = animator.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            var right = animator.GetBoneTransform(HumanBodyBones.RightUpperArm);
            if (left == null || right == null) return;

            var across = right.position - left.position;
            across.y = 0f;
            if (across.sqrMagnitude < 1e-6f) return;
            var bodyForward = Vector3.Cross(across, Vector3.up).normalized;

            // low-pass the measured forward and keep a dead zone: the mocap's
            // weight shifts sway the shoulder line, and chasing that sway at
            // full rate reads as rhythmic twitching
            smoothedForward = smoothedForward == Vector3.zero
                ? bodyForward
                : Vector3.Slerp(smoothedForward, bodyForward,
                    1f - Mathf.Exp(-3f * Time.deltaTime));

            var toCamera = camera.transform.position - transform.position;
            toCamera.y = 0f;
            if (toCamera.sqrMagnitude < 1e-6f) return;

            var delta = Vector3.SignedAngle(smoothedForward, toCamera, Vector3.up);
            if (Mathf.Abs(delta) < deadZoneDegrees) return;
            var step = Mathf.Clamp(delta, -degreesPerSecond * Time.deltaTime,
                degreesPerSecond * Time.deltaTime);
            transform.Rotate(0f, step, 0f, Space.World);
        }
    }
}
