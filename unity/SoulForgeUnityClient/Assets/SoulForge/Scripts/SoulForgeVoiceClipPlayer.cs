using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

namespace SoulForge.UnityClient
{
    public class SoulForgeVoiceClipPlayer : MonoBehaviour
    {
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private AudioSource audioSource;
        [SerializeField] private string voiceRoot;

        private void Reset()
        {
            audioSource = GetComponent<AudioSource>();
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

        private void HandleEvent(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (audioSource == null || behaviorEvent == null || string.IsNullOrWhiteSpace(behaviorEvent.voiceClipPath))
            {
                return;
            }

            StartCoroutine(LoadAndPlay(ResolvePath(behaviorEvent.voiceClipPath)));
        }

        private string ResolvePath(string clipPath)
        {
            if (Path.IsPathRooted(clipPath) || clipPath.StartsWith("file://"))
            {
                return clipPath;
            }

            if (!string.IsNullOrWhiteSpace(voiceRoot))
            {
                return Path.Combine(voiceRoot, clipPath);
            }

            return Path.Combine(Application.streamingAssetsPath, clipPath);
        }

        private IEnumerator LoadAndPlay(string path)
        {
            var url = path.StartsWith("file://") ? path : "file://" + path;
            using (var request = UnityWebRequestMultimedia.GetAudioClip(url, AudioType.UNKNOWN))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Debug.LogWarning("Failed to load SoulForge voice clip: " + request.error);
                    yield break;
                }

                audioSource.clip = DownloadHandlerAudioClip.GetContent(request);
                audioSource.Play();
            }
        }
    }
}
