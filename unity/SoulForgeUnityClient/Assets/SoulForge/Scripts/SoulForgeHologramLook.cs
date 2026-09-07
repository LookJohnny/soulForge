using System.Collections.Generic;
using UnityEngine;

namespace SoulForge.UnityClient
{
    /// <summary>
    /// Blade-Runner-style hologram, toggled with H. Swaps every renderer to the
    /// SoulForge/Hologram shader (fresnel rim + scanlines + flicker), and makes
    /// the character a light source: magenta/cyan point lights that pulse while
    /// she speaks. Originals restored on toggle-off.
    /// </summary>
    public class SoulForgeHologramLook : MonoBehaviour
    {
        [SerializeField] private KeyCode toggleKey = KeyCode.H;
        [SerializeField] private bool startActive;
        [SerializeField] private Color tint = new Color(0.55f, 0.75f, 1.0f, 0.30f);
        [SerializeField] private Color rim = new Color(1.0f, 0.35f, 0.75f);

        private readonly Dictionary<Renderer, Material[]> originals = new();
        private Material hologram;
        private Light glowMagenta;
        private Light glowCyan;
        private SoulForgeVrmPresence presence;
        private bool active;

        private void Start()
        {
            presence = GetComponent<SoulForgeVrmPresence>();
            if (startActive) Apply();
        }

        private void Update()
        {
            if (Input.GetKeyDown(toggleKey))
            {
                if (active) Restore();
                else Apply();
            }
            if (active && glowMagenta != null)
            {
                // she is the light source: breathe slowly, surge while speaking
                var speaking = presence != null && presence.IsSpeaking;
                var pulse = 0.9f + 0.1f * Mathf.Sin(Time.time * 1.7f)
                    + (speaking ? 0.35f + 0.20f * Mathf.Sin(Time.time * 9f) : 0f);
                glowMagenta.intensity = 1.6f * pulse;
                glowCyan.intensity = 0.9f * pulse;
            }
        }

        private void Apply()
        {
            if (hologram == null)
            {
                var shader = Shader.Find("SoulForge/Hologram");
                if (shader != null)
                {
                    hologram = new Material(shader);
                    hologram.SetColor("_BaseColor", tint);
                    hologram.SetColor("_RimColor", rim);
                }
                else
                {
                    // fallback: translucent URP Lit ghost
                    var lit = Shader.Find("Universal Render Pipeline/Lit");
                    if (lit == null) return;
                    hologram = new Material(lit);
                    hologram.SetFloat("_Surface", 1f);
                    hologram.SetFloat("_ZWrite", 0f);
                    hologram.SetOverrideTag("RenderType", "Transparent");
                    hologram.renderQueue = (int)UnityEngine.Rendering.RenderQueue.Transparent;
                    hologram.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
                    hologram.EnableKeyword("_EMISSION");
                    hologram.SetColor("_BaseColor", tint);
                    hologram.SetColor("_EmissionColor", (Vector4)rim * 1.6f);
                }
            }
            foreach (var renderer in GetComponentsInChildren<Renderer>())
            {
                if (originals.ContainsKey(renderer)) continue;
                originals[renderer] = renderer.sharedMaterials;
                var swapped = new Material[renderer.sharedMaterials.Length];
                for (var i = 0; i < swapped.Length; i++) swapped[i] = hologram;
                renderer.sharedMaterials = swapped;
            }
            if (glowMagenta == null)
            {
                glowMagenta = MakeGlow("Holo Glow Magenta", rim, new Vector3(0f, 1.25f, 0.15f), 4.5f);
                glowCyan = MakeGlow("Holo Glow Cyan", new Color(0.35f, 0.85f, 1.0f), new Vector3(0f, 0.35f, -0.2f), 3.0f);
            }
            glowMagenta.gameObject.SetActive(true);
            glowCyan.gameObject.SetActive(true);
            active = true;
        }

        private Light MakeGlow(string name, Color color, Vector3 localPosition, float range)
        {
            var holder = new GameObject(name);
            holder.transform.SetParent(transform, false);
            holder.transform.localPosition = localPosition;
            var light = holder.AddComponent<Light>();
            light.type = LightType.Point;
            light.color = color;
            light.range = range;
            light.intensity = 1.2f;
            light.shadows = LightShadows.None;
            return light;
        }

        private void Restore()
        {
            foreach (var pair in originals)
            {
                if (pair.Key != null) pair.Key.sharedMaterials = pair.Value;
            }
            originals.Clear();
            if (glowMagenta != null) glowMagenta.gameObject.SetActive(false);
            if (glowCyan != null) glowCyan.gameObject.SetActive(false);
            active = false;
        }
    }
}
