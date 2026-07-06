using UnityEngine;
using UnityEngine.UI;

namespace SoulForge.UnityClient
{
    public class SoulForgeDialogueHud : MonoBehaviour
    {
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private Text speakerText;
        [SerializeField] private Text dialogueText;
        [SerializeField] private Text metaText;

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

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent == null || string.IsNullOrWhiteSpace(behaviorEvent.dialogue))
            {
                return;
            }

            if (speakerText != null)
            {
                speakerText.text = string.IsNullOrWhiteSpace(behaviorEvent.agentName) ? behaviorEvent.agentId : behaviorEvent.agentName;
            }

            if (dialogueText != null)
            {
                dialogueText.text = behaviorEvent.dialogue;
            }

            if (metaText != null)
            {
                metaText.text = behaviorEvent.emotion + " / " + behaviorEvent.actionTemplateId;
            }
        }
    }
}
