using System;
using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeBridge : MonoBehaviour
    {
        [SerializeField] private TextAsset replayJson;
        [SerializeField] private bool loopReplay = true;
        [SerializeField] private float playbackSpeed = 1.0f;

        public event Action<SoulForgeBehaviorEvent> EventReceived;

        private readonly List<SoulForgeBehaviorEvent> events = new List<SoulForgeBehaviorEvent>();
        private float startedAt;
        private int cursor;
        private float replayDuration;

        private void Awake()
        {
            LoadReplayAsset();
        }

        private void OnEnable()
        {
            startedAt = Time.time;
            cursor = 0;
        }

        private void Update()
        {
            if (events.Count == 0)
            {
                return;
            }

            var elapsed = (Time.time - startedAt) * playbackSpeed;
            if (loopReplay && replayDuration > 0.01f)
            {
                elapsed %= replayDuration;
                while (cursor > 0 && events[cursor - 1].time > elapsed)
                {
                    cursor--;
                }
            }

            while (cursor < events.Count && events[cursor].time <= elapsed)
            {
                EventReceived?.Invoke(events[cursor]);
                cursor++;
            }
        }

        public void Publish(SoulForgeBehaviorEvent behaviorEvent)
        {
            if (behaviorEvent != null)
            {
                EventReceived?.Invoke(behaviorEvent);
            }
        }

        public void PublishJson(string json)
        {
            if (string.IsNullOrWhiteSpace(json))
            {
                return;
            }

            var behaviorEvent = JsonUtility.FromJson<SoulForgeBehaviorEvent>(json);
            Publish(behaviorEvent);
        }

        public void LoadReplayJson(string json)
        {
            events.Clear();
            if (string.IsNullOrWhiteSpace(json))
            {
                return;
            }

            var wrapped = JsonUtility.FromJson<SoulForgeBehaviorEventList>(json);
            if (wrapped?.events == null)
            {
                return;
            }

            events.AddRange(wrapped.events);
            events.Sort((a, b) => a.time.CompareTo(b.time));
            replayDuration = events.Count == 0 ? 0 : events[events.Count - 1].time + 1.0f;
        }

        private void LoadReplayAsset()
        {
            if (replayJson != null)
            {
                LoadReplayJson(replayJson.text);
            }
        }
    }
}
