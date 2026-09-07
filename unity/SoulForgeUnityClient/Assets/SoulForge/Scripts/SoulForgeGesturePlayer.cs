using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// Plays mocap gestures (Mixamo library) with animator crossfades.
    ///
    /// A beat step whose name matches a gesture state crossfades in for the
    /// clip's length, then crossfades back to idle — smooth entry and release,
    /// full-body motion. Steps without a mocap state fall through to the
    /// procedural animator as before.
    /// </summary>
    public class SoulForgeGesturePlayer : MonoBehaviour
    {
        [SerializeField] private string agentId;
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private float fadeIn = 0.25f;
        [SerializeField] private float fadeOut = 0.35f;

        // step names produced by SoulForgeSceneBuilder.BuildGestureLibrary
        private static readonly HashSet<string> Gestures = new()
        {
            "crouch", "stand_up", "point_at", "flirt", "dance_belly", "blow_kiss",
            "think_pose", "excited", "dance", "dance_rumba", "sad_idle",
            "walk_loop", "walk_turn", "idle_alt", "look_around_big", "greeting",
        };

        private Animator animator;
        private float returnAt = -1f;

        private void OnEnable()
        {
            animator = GetComponentInChildren<Animator>();
            if (bridge != null) bridge.EventReceived += HandleEvent;
        }

        private void OnDisable()
        {
            if (bridge != null) bridge.EventReceived -= HandleEvent;
        }

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent == null || behaviorEvent.agentId != agentId) return;
            if (animator == null || animator.runtimeAnimatorController == null) return;

            var id = behaviorEvent.actionTemplateId ?? "";
            var colon = id.LastIndexOf(':');
            var step = colon >= 0 ? id.Substring(colon + 1) : id;
            if (!Gestures.Contains(step)) return;
            if (!animator.HasState(0, Animator.StringToHash(step))) return;

            animator.CrossFadeInFixedTime(step, fadeIn);
            returnAt = Time.time + ClipLength(step);
        }

        private float ClipLength(string stateName)
        {
            foreach (var clip in animator.runtimeAnimatorController.animationClips)
            {
                if (clip.name == stateName)
                {
                    // looping clips (dances, crouch idle) hold for a while, one-shots play out
                    return clip.isLooping ? Mathf.Max(clip.length, 6f) : Mathf.Max(clip.length - 0.2f, 0.8f);
                }
            }
            return 3f;
        }

        private void Update()
        {
            if (returnAt > 0f && Time.time >= returnAt)
            {
                returnAt = -1f;
                if (animator != null && animator.runtimeAnimatorController != null
                    && animator.HasState(0, Animator.StringToHash("idle")))
                {
                    animator.CrossFadeInFixedTime("idle", fadeOut);
                }
            }
        }
    }
}
