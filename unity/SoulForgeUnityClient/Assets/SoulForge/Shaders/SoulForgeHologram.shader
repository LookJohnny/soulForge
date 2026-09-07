// Blade-Runner-style hologram: fresnel rim glow, drifting scanlines, low-frequency
// flicker with occasional glitch. Additive-leaning transparency so she reads as a
// light source; pair with a point light + bloom for the volumetric halo.
Shader "SoulForge/Hologram"
{
    Properties
    {
        _BaseColor ("Base Color", Color) = (0.55, 0.75, 1.0, 0.30)
        _RimColor ("Rim Color", Color) = (1.0, 0.35, 0.75, 1.0)
        _RimPower ("Rim Power", Range(0.5, 8)) = 2.6
        _ScanDensity ("Scanline Density", Range(10, 400)) = 140
        _ScanSpeed ("Scanline Speed", Range(0, 10)) = 1.6
        _FlickerSpeed ("Flicker Speed", Range(0, 60)) = 22
        _GlitchStrength ("Glitch Strength", Range(0, 0.05)) = 0.012
        _Brightness ("Brightness", Range(0.2, 4)) = 1.6
    }
    SubShader
    {
        Tags { "RenderType" = "Transparent" "Queue" = "Transparent" "RenderPipeline" = "UniversalPipeline" }
        Pass
        {
            Name "Forward"
            Blend SrcAlpha One
            ZWrite Off
            Cull Back

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            CBUFFER_START(UnityPerMaterial)
                half4 _BaseColor;
                half4 _RimColor;
                half _RimPower;
                half _ScanDensity;
                half _ScanSpeed;
                half _FlickerSpeed;
                half _GlitchStrength;
                half _Brightness;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS : NORMAL;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
            };

            Varyings vert(Attributes input)
            {
                Varyings output;
                float3 positionWS = TransformObjectToWorld(input.positionOS.xyz);

                // occasional horizontal glitch bands sweeping upward
                float t = _Time.y;
                float band = frac(positionWS.y * 3.1 - t * 0.7);
                float burst = step(0.992, frac(sin(floor(t * 2.3)) * 43758.5453));
                positionWS.x += _GlitchStrength * burst * step(0.5, band) * sin(positionWS.y * 90.0 + t * 40.0);

                output.positionWS = positionWS;
                output.positionCS = TransformWorldToHClip(positionWS);
                output.normalWS = TransformObjectToWorldNormal(input.normalOS);
                return output;
            }

            half4 frag(Varyings input) : SV_Target
            {
                float3 normalWS = normalize(input.normalWS);
                float3 viewDirWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
                half fresnel = pow(1.0 - saturate(dot(normalWS, viewDirWS)), _RimPower);

                float t = _Time.y;
                half scan = 0.72 + 0.28 * sin(input.positionWS.y * _ScanDensity - t * _ScanSpeed * 6.2831);
                half fineScan = 0.92 + 0.08 * sin(input.positionWS.y * _ScanDensity * 3.7);
                half flicker = 0.93 + 0.05 * sin(t * _FlickerSpeed) + 0.02 * sin(t * _FlickerSpeed * 3.7 + 1.3);

                half3 color = (_BaseColor.rgb + _RimColor.rgb * fresnel * 2.2)
                    * scan * fineScan * flicker * _Brightness;
                half alpha = saturate((_BaseColor.a + fresnel * 0.55) * scan * flicker);
                return half4(color, alpha);
            }
            ENDHLSL
        }
    }
    FallBack Off
}
