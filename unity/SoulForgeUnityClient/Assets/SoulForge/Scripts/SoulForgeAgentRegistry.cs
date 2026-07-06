using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeAgentRegistry : MonoBehaviour
    {
        private static readonly Dictionary<string, Transform> Agents = new Dictionary<string, Transform>();

        [SerializeField] private string agentId;

        private void OnEnable()
        {
            Register(agentId, transform);
        }

        private void OnDisable()
        {
            Unregister(agentId, transform);
        }

        public static void Register(string id, Transform target)
        {
            if (!string.IsNullOrWhiteSpace(id) && target != null)
            {
                Agents[id] = target;
            }
        }

        public static void Unregister(string id, Transform target)
        {
            if (!string.IsNullOrWhiteSpace(id) && Agents.ContainsKey(id) && Agents[id] == target)
            {
                Agents.Remove(id);
            }
        }

        public static bool TryGetAgent(string id, out Transform target)
        {
            if (string.IsNullOrWhiteSpace(id))
            {
                target = null;
                return false;
            }

            return Agents.TryGetValue(id, out target);
        }
    }
}
