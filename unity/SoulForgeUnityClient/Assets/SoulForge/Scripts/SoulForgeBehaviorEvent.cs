using System;
using UnityEngine;

namespace SoulForge.UnityClient
{
    [Serializable]
    public class SoulForgeVector3
    {
        public float x;
        public float y;
        public float z;

        public Vector3 ToUnityVector3()
        {
            return new Vector3(x, y, z);
        }
    }

    [Serializable]
    public class SoulForgeBehaviorEvent
    {
        public float time;
        public string agentId;
        public string agentName;
        public string actionTemplateId;
        public string dialogue;
        public string emotion;
        public string cameraShot;
        public string lookAtAgentId;
        public SoulForgeVector3 targetPosition;
        public string voiceClipPath;
        public string priority;
    }

    [Serializable]
    public class SoulForgeBehaviorEventList
    {
        public SoulForgeBehaviorEvent[] events;
    }
}
