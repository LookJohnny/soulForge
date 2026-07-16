using System;

namespace SoulForge.UnityClient
{
    // SoulForge Protocol 0.2 wire DTOs (JsonUtility-friendly subset).
    //
    // JsonUtility cannot represent open dictionaries, so free-form fields of the
    // canonical IR (params / adapter_command / trace_context / sensor_snapshot)
    // are intentionally NOT declared here — JsonUtility simply ignores them on
    // parse, which matches the protocol's forward-compatibility rule. The Unity
    // runtime executes actions from `name` + `template_id` + scalar fields.

    [Serializable]
    public class ProtocolTypeProbe
    {
        public string type;
    }

    [Serializable]
    public class ManifestFeatures
    {
        public bool speech = true;
        public bool gaze = true;
        public bool nav = true;
    }

    [Serializable]
    public class EmbodimentManifestMsg
    {
        public string body_id;
        public string backend = "unity";
        public string[] supported_steps = new string[0];      // empty = virtual body claims all
        public string[] supported_templates = new string[0];
        public ManifestFeatures features = new ManifestFeatures();
    }

    [Serializable]
    public class BodyHelloMsg
    {
        public string type = "hello";
        public string protocol = "0.2";
        public string body_id;
        public string backend = "unity";
        public string[] agent_ids;
        public EmbodimentManifestMsg manifest;
    }

    [Serializable]
    public class WelcomeMsg
    {
        public string type;
        public string body_id;
        public string[] accepted_agents;
        public string[] supported_steps;
        public string protocol;
    }

    [Serializable]
    public class ActionCommandMsg
    {
        public string type;
        public string agent_id;
        public string name;
        public string template_id;
        public string dialogue;
        public string gaze_target;
        public float duration_s = 2f;
        public float sim_minute;
        public string command_id;
        public string protocol_version;
        public string correlation_id;
        public int sequence;
        public string target_body;
        public int priority = 50;
        public float issued_at;
        public float deadline = -1f;    // JSON null parses as default; -1 = unset sentinel
        public float ttl_s = 30f;
        public bool interruptible = true;
        public string safety_class;
        public string ack_policy;
    }

    [Serializable]
    public class ObservationMsg
    {
        public string type = "observation";
        public string command_id;
        public string agent_id;
        public string status;           // accepted|running|done|failed|interrupted|rejected
        public string detail = "";
        public string body_id;
        public float started_at;
        public float finished_at;
        public string error_code;
        public bool recoverable = true;
    }

    [Serializable]
    public class TickMsg
    {
        public string type;
        public float sim_minute;
        public string clock;
    }

    [Serializable]
    public class PlanStateMsg
    {
        public string type;
        public string agent_id;
        public string clock;
        public string hour_goal;
    }
}
