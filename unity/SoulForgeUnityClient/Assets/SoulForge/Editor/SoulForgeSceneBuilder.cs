#if UNITY_EDITOR
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;
using UnityEngine.UI;

namespace SoulForge.UnityClient.Editor
{
    public static class SoulForgeSceneBuilder
    {
        private const string ScenePath = "Assets/SoulForge/Scenes/SoulForgeApartment.unity";
        private const int PreviewWidth = 1280;
        private const int PreviewHeight = 720;
        private const int DemoFrameCount = 360;
        private const int DemoFps = 12;
        private const string KenneyFurnitureRoot = "Assets/ThirdParty/KenneyFurniture/FBX/";
        private const string KenneyMiniCharacterRoot = "Assets/ThirdParty/KenneyMiniCharacters/OBJ/";
        private const string KenneyMiniPreviewRoot = "Assets/ThirdParty/KenneyMiniCharacters/Previews/";
        private const string KenneyCharacterModel = "Assets/ThirdParty/KenneyCharacters3/Model/characterMedium.fbx";
        private const string KenneyCharacterSkinRoot = "Assets/ThirdParty/KenneyCharacters3/Skins/";

        private static readonly string[] ShotNames =
        {
            "wide", "coffee", "kitchen", "plant", "conversation", "sketch", "desk", "repair", "dance", "sofa"
        };

        [MenuItem("SoulForge/Create Apartment Demo Scene")]
        public static void CreateApartmentDemoScene()
        {
            AssetDatabase.Refresh();

            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var materials = CreateMaterials();

            CreateEnvironment(materials);

            var bridge = new GameObject("SoulForgeBridge").AddComponent<SoulForgeBridge>();
            SetObject(bridge, "replayJson", AssetDatabase.LoadAssetAtPath<TextAsset>("Assets/SoulForge/Samples/replay_events.json"));

            var camera = CreateMainCamera();
            CreateCinematicPostProcess();
            var shotAnchors = CreateCameraShots();
            var director = new GameObject("SoulForgeDirector").AddComponent<SoulForgeTimelineDirector>();
            SetObject(director, "bridge", bridge);
            SetObject(director, "targetCamera", camera);
            SetObject(director, "defaultShot", shotAnchors[0]);
            SetShots(director, shotAnchors);

            CreateAstra(bridge, materials);
            CreateMason(bridge, materials);
            CreateHex(bridge, materials);
            CreateHud(bridge);

            Directory.CreateDirectory("Assets/SoulForge/Scenes");
            EditorSceneManager.SaveScene(scene, ScenePath);
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
            Selection.activeObject = bridge.gameObject;
        }

        [MenuItem("SoulForge/Capture Apartment Preview")]
        public static void CaptureApartmentPreview()
        {
            if (!File.Exists(ScenePath))
            {
                CreateApartmentDemoScene();
            }

            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var camera = Camera.main != null ? Camera.main : Object.FindObjectOfType<Camera>();
            if (camera == null)
            {
                throw new InvalidDataException("SoulForge apartment preview requires a scene camera.");
            }

            var previousTarget = camera.targetTexture;
            var previousActive = RenderTexture.active;
            var renderTexture = new RenderTexture(PreviewWidth, PreviewHeight, 24);
            var texture = new Texture2D(PreviewWidth, PreviewHeight, TextureFormat.RGB24, false);

            try
            {
                camera.targetTexture = renderTexture;
                RenderTexture.active = renderTexture;
                camera.Render();
                texture.ReadPixels(new Rect(0, 0, PreviewWidth, PreviewHeight), 0, 0);
                texture.Apply();

                var outputPath = Path.GetFullPath(Path.Combine(
                    Application.dataPath,
                    "../../..",
                    "outputs/unity/soulforge_unity_apartment_preview.png"
                ));
                Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
                File.WriteAllBytes(outputPath, texture.EncodeToPNG());
                Debug.Log("SoulForge apartment preview written to " + outputPath);
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                Object.DestroyImmediate(texture);
                Object.DestroyImmediate(renderTexture);
            }
        }

        [MenuItem("SoulForge/Capture Apartment Demo Frames")]
        public static void CaptureApartmentDemoFrames()
        {
            if (!File.Exists(ScenePath))
            {
                CreateApartmentDemoScene();
            }

            EditorSceneManager.OpenScene(ScenePath, OpenSceneMode.Single);
            var camera = Camera.main != null ? Camera.main : Object.FindObjectOfType<Camera>();
            if (camera == null)
            {
                throw new InvalidDataException("SoulForge apartment demo capture requires a scene camera.");
            }

            var outputDir = Path.GetFullPath(Path.Combine(
                Application.dataPath,
                "../../..",
                "outputs/unity/apartment_demo_frames"
            ));
            Directory.CreateDirectory(outputDir);
            foreach (var oldFrame in Directory.GetFiles(outputDir, "frame_*.png"))
            {
                File.Delete(oldFrame);
            }

            var previousTarget = camera.targetTexture;
            var previousActive = RenderTexture.active;
            var renderTexture = new RenderTexture(PreviewWidth, PreviewHeight, 24);
            var texture = new Texture2D(PreviewWidth, PreviewHeight, TextureFormat.RGB24, false);

            try
            {
                for (var frame = 0; frame < DemoFrameCount; frame++)
                {
                    var elapsed = frame / (float)DemoFps;
                    ApplyDemoActions(elapsed);
                    ApplyDemoCamera(camera, frame / (float)(DemoFrameCount - 1));

                    camera.targetTexture = renderTexture;
                    RenderTexture.active = renderTexture;
                    camera.Render();
                    texture.ReadPixels(new Rect(0, 0, PreviewWidth, PreviewHeight), 0, 0);
                    texture.Apply();
                    File.WriteAllBytes(Path.Combine(outputDir, "frame_" + frame.ToString("0000") + ".png"), texture.EncodeToPNG());
                }

                Debug.Log("SoulForge apartment demo frames written to " + outputDir);
            }
            finally
            {
                camera.targetTexture = previousTarget;
                RenderTexture.active = previousActive;
                Object.DestroyImmediate(texture);
                Object.DestroyImmediate(renderTexture);
            }
        }

        private static void ApplyDemoActions(float elapsed)
        {
            var segment = Mathf.FloorToInt(elapsed / 2.0f) % 4;
            var astra = GameObject.Find("Astra-F");
            var mason = GameObject.Find("Mason-M");
            var hex = GameObject.Find("Hex-01");

            SetDemoAgentPosition(astra, new Vector3(-2.34f + Mathf.Sin(elapsed * 1.1f) * 0.05f, 0, 0.42f));
            SetDemoAgentPosition(mason, new Vector3(-0.18f + Mathf.Sin(elapsed * 0.9f) * 0.04f, 0, -0.18f));
            SetDemoAgentPosition(hex, new Vector3(1.24f + Mathf.Sin(elapsed * 1.4f) * 0.04f, 0, -0.10f));

            PreviewAgent(astra, segment == 0 ? "sketch" : segment == 1 ? "talk" : segment == 2 ? "dance" : "coffee", elapsed);
            PreviewAgent(mason, segment == 0 ? "cook" : segment == 1 ? "talk" : segment == 2 ? "desk" : "call", elapsed);
            PreviewAgent(hex, segment == 0 ? "scan" : segment == 1 ? "repair" : segment == 2 ? "dance" : "scan", elapsed);
        }

        private static void PreviewAgent(GameObject agent, string action, float elapsed)
        {
            if (agent == null)
            {
                return;
            }

            var animator = agent.GetComponent<SoulForgeProceduralAgentAnimator>();
            if (animator != null)
            {
                animator.PreviewAction(action, elapsed);
            }
        }

        private static void SetDemoAgentPosition(GameObject agent, Vector3 position)
        {
            if (agent != null)
            {
                agent.transform.position = position;
            }
        }

        private static void ApplyDemoCamera(Camera camera, float normalized)
        {
            var sequence = new[] { "wide", "kitchen", "plant", "sketch", "conversation", "sofa", "wide" };
            var scaled = Mathf.Clamp01(normalized) * (sequence.Length - 1);
            var index = Mathf.Min(Mathf.FloorToInt(scaled), sequence.Length - 2);
            var blend = Smooth01(scaled - index);
            var from = FindShot(sequence[index]);
            var to = FindShot(sequence[index + 1]);
            if (from == null || to == null)
            {
                return;
            }

            camera.transform.position = Vector3.Lerp(from.position, to.position, blend);
            camera.transform.rotation = Quaternion.Slerp(from.rotation, to.rotation, blend);
        }

        private static Transform FindShot(string name)
        {
            var root = GameObject.Find("CameraShots");
            return root == null ? null : root.transform.Find(name);
        }

        private static float Smooth01(float value)
        {
            value = Mathf.Clamp01(value);
            return value * value * (3.0f - 2.0f * value);
        }

        private static Camera CreateMainCamera()
        {
            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            cameraObject.transform.position = new Vector3(-1.20f, 1.32f, -4.05f);
            cameraObject.transform.LookAt(new Vector3(-0.04f, 0.94f, 0.08f));

            var camera = cameraObject.AddComponent<Camera>();
            camera.fieldOfView = 43;
            camera.allowHDR = true;
            camera.allowMSAA = true;
            camera.backgroundColor = new Color(0.010f, 0.014f, 0.022f);

            var cameraData = cameraObject.AddComponent<UniversalAdditionalCameraData>();
            cameraData.renderPostProcessing = true;
            cameraData.antialiasing = AntialiasingMode.FastApproximateAntialiasing;
            return camera;
        }

        private static void CreateCinematicPostProcess()
        {
            var volumeObject = new GameObject("Cinematic Post Volume");
            var volume = volumeObject.AddComponent<Volume>();
            volume.isGlobal = true;
            volume.priority = 10.0f;

            var profile = ScriptableObject.CreateInstance<VolumeProfile>();
            profile.name = "SoulForge_Cinematic_Post";
            volume.sharedProfile = profile;

            var bloom = profile.Add<Bloom>(true);
            bloom.threshold.Override(0.78f);
            bloom.intensity.Override(0.62f);
            bloom.scatter.Override(0.58f);

            var vignette = profile.Add<Vignette>(true);
            vignette.intensity.Override(0.32f);
            vignette.smoothness.Override(0.56f);

            var color = profile.Add<ColorAdjustments>(true);
            color.postExposure.Override(0.22f);
            color.contrast.Override(22.0f);
            color.saturation.Override(10.0f);
            color.colorFilter.Override(new Color(1.0f, 0.93f, 0.84f));

            var whiteBalance = profile.Add<WhiteBalance>(true);
            whiteBalance.temperature.Override(14.0f);
            whiteBalance.tint.Override(4.0f);
        }

        private static Transform[] CreateCameraShots()
        {
            var shotRoot = new GameObject("CameraShots").transform;
            var shotAnchors = new Transform[ShotNames.Length];
            for (var i = 0; i < ShotNames.Length; i++)
            {
                var anchor = new GameObject(ShotNames[i]).transform;
                anchor.SetParent(shotRoot, false);
                anchor.localPosition = ShotPosition(ShotNames[i]);
                anchor.LookAt(ShotLookAt(ShotNames[i]));
                shotAnchors[i] = anchor;
            }

            return shotAnchors;
        }

        private static void CreateEnvironment(SceneMaterials materials)
        {
            var root = new GameObject("Apartment_Set").transform;

            CreateBox("Floor", root, new Vector3(0, -0.04f, 0), new Vector3(7.6f, 0.08f, 4.9f), materials.floor);
            CreateBox("Back Wall", root, new Vector3(0, 1.48f, 2.38f), new Vector3(7.6f, 2.96f, 0.10f), materials.wall);
            CreateBox("Left Wall", root, new Vector3(-3.8f, 1.48f, 0), new Vector3(0.10f, 2.96f, 4.9f), materials.wall);
            CreateBox("Ceiling Plane", root, new Vector3(0, 2.93f, 0), new Vector3(7.6f, 0.06f, 4.9f), materials.ceiling);

            for (var i = 0; i < 15; i++)
            {
                CreateBox("Floor Plank " + i, root, new Vector3(-3.45f + i * 0.50f, 0.006f, -0.05f), new Vector3(0.018f, 0.012f, 4.75f), materials.floorLine);
            }

            CreateWindowWall(root, materials);
            CreateKitchen(root, materials);
            CreateDeskZone(root, materials);
            CreateSofaZone(root, materials);
            CreatePlantZone(root, materials);
            CreateShelves(root, materials);
            CreateLighting(root, materials);
            CreateDiegeticHud(root, materials);

            RenderSettings.ambientLight = new Color(0.065f, 0.075f, 0.095f);
            RenderSettings.fog = true;
            RenderSettings.fogColor = new Color(0.012f, 0.018f, 0.026f);
            RenderSettings.fogDensity = 0.012f;
        }

        private static void CreateWindowWall(Transform root, SceneMaterials materials)
        {
            CreateBox("Night Window Glass", root, new Vector3(1.55f, 1.52f, 2.30f), new Vector3(2.75f, 1.48f, 0.035f), materials.window);
            CreateBox("Window Frame Top", root, new Vector3(1.55f, 2.28f, 2.25f), new Vector3(2.9f, 0.035f, 0.06f), materials.blackMetal);
            CreateBox("Window Frame Bottom", root, new Vector3(1.55f, 0.76f, 2.25f), new Vector3(2.9f, 0.035f, 0.06f), materials.blackMetal);
            CreateBox("Window Frame Left", root, new Vector3(0.12f, 1.52f, 2.25f), new Vector3(0.035f, 1.55f, 0.06f), materials.blackMetal);
            CreateBox("Window Frame Right", root, new Vector3(2.98f, 1.52f, 2.25f), new Vector3(0.035f, 1.55f, 0.06f), materials.blackMetal);
            CreateBox("Window Mullion", root, new Vector3(1.55f, 1.52f, 2.24f), new Vector3(0.026f, 1.50f, 0.06f), materials.blackMetal);

            for (var i = 0; i < 18; i++)
            {
                var x = 0.35f + (i % 6) * 0.46f;
                var y = 0.95f + (i / 6) * 0.34f;
                var height = 0.10f + (i % 3) * 0.06f;
                CreateBox("City Light " + i, root, new Vector3(x, y, 2.22f), new Vector3(0.08f, height, 0.025f), i % 2 == 0 ? materials.cityWarm : materials.cityCool);
            }

            CreateBox("SoulForge Neon Stem A", root, new Vector3(-2.05f, 1.58f, 2.25f), new Vector3(0.90f, 0.035f, 0.035f), materials.neon);
            CreateBox("SoulForge Neon Stem B", root, new Vector3(-1.74f, 1.36f, 2.25f), new Vector3(0.035f, 0.46f, 0.035f), materials.neon);
            CreateBox("SoulForge Neon Stem C", root, new Vector3(-1.55f, 1.22f, 2.25f), new Vector3(0.70f, 0.035f, 0.035f), materials.neon);
        }

        private static void CreateKitchen(Transform root, SceneMaterials materials)
        {
            if (PlaceKenneyAsset("Kitchen Island Model", root, "kitchenBar", new Vector3(-0.30f, 0.0f, -0.80f), new Vector3(2.45f, 0.95f, 0.86f), new Vector3(0, 180, 0), materials.wood) == null)
            {
                CreateBox("Kitchen Island", root, new Vector3(-0.30f, 0.50f, -0.80f), new Vector3(2.45f, 0.92f, 0.86f), materials.wood);
            }

            CreateBox("Kitchen Countertop Highlight", root, new Vector3(-0.30f, 1.01f, -0.80f), new Vector3(2.30f, 0.035f, 0.76f), materials.counter);
            CreateBox("Cooktop", root, new Vector3(0.10f, 1.035f, -0.88f), new Vector3(0.62f, 0.018f, 0.42f), materials.blackGlass);
            CreateCylinder("Pan", root, new Vector3(0.10f, 1.09f, -0.88f), new Vector3(0.30f, 0.035f, 0.30f), materials.blackMetal, Vector3.zero);
            CreateCylinder("Pan Handle", root, new Vector3(0.47f, 1.09f, -0.88f), new Vector3(0.035f, 0.21f, 0.035f), materials.blackMetal, new Vector3(0, 0, 90));
            CreateCylinder("Cup On Island", root, new Vector3(-1.05f, 1.09f, -0.66f), new Vector3(0.09f, 0.10f, 0.09f), materials.ceramic, Vector3.zero);
            CreateBox("Cutting Board", root, new Vector3(-0.62f, 1.045f, -1.02f), new Vector3(0.44f, 0.025f, 0.30f), materials.lightWood);
            CreateSphere("Tomato", root, new Vector3(-0.50f, 1.08f, -1.03f), new Vector3(0.07f, 0.07f, 0.07f), materials.red);
            CreateSphere("Lettuce", root, new Vector3(-0.68f, 1.08f, -1.05f), new Vector3(0.09f, 0.05f, 0.08f), materials.leaf);

            PlaceKenneyAsset("Back Kitchen Cabinet", root, "kitchenCabinet", new Vector3(-2.35f, 0.0f, 2.13f), new Vector3(0.70f, 0.92f, 0.30f), new Vector3(0, 180, 0), materials.cabinet);
            PlaceKenneyAsset("Back Kitchen Drawer", root, "kitchenCabinetDrawer", new Vector3(-1.66f, 0.0f, 2.13f), new Vector3(0.62f, 0.92f, 0.30f), new Vector3(0, 180, 0), materials.cabinet);
            PlaceKenneyAsset("Kitchen Sink Asset", root, "kitchenSink", new Vector3(-2.02f, 0.0f, 1.86f), new Vector3(0.58f, 0.88f, 0.36f), new Vector3(0, 180, 0), materials.counter);
            PlaceKenneyAsset("Kitchen Stove Asset", root, "kitchenStove", new Vector3(-1.18f, 0.0f, 1.88f), new Vector3(0.62f, 0.88f, 0.38f), new Vector3(0, 180, 0), materials.blackMetal);
            PlaceKenneyAsset("Kitchen Fridge Asset", root, "kitchenFridgeLarge", new Vector3(-0.52f, 0.0f, 2.08f), new Vector3(0.52f, 1.72f, 0.38f), new Vector3(0, 180, 0), materials.fridge);
            PlaceKenneyAsset("Coffee Machine", root, "kitchenCoffeeMachine", new Vector3(0.48f, 1.02f, -1.05f), new Vector3(0.26f, 0.28f, 0.22f), new Vector3(0, 22, 0), materials.blackMetal);
            PlaceKenneyAsset("Bar Stool A", root, "stoolBar", new Vector3(-0.84f, 0.0f, -1.48f), new Vector3(0.28f, 0.58f, 0.28f), new Vector3(0, 10, 0), materials.blackMetal);
            PlaceKenneyAsset("Bar Stool B", root, "stoolBarSquare", new Vector3(0.12f, 0.0f, -1.48f), new Vector3(0.28f, 0.58f, 0.28f), new Vector3(0, -10, 0), materials.blackMetal);
            CreateBox("Fridge Note A", root, new Vector3(-1.05f, 1.48f, 2.03f), new Vector3(0.12f, 0.09f, 0.018f), materials.cityWarm);
            CreateBox("Fridge Note B", root, new Vector3(-0.82f, 1.25f, 2.03f), new Vector3(0.10f, 0.12f, 0.018f), materials.pink);
        }

        private static void CreateDeskZone(Transform root, SceneMaterials materials)
        {
            if (PlaceKenneyAsset("Creator Desk Model", root, "desk", new Vector3(-2.35f, 0.0f, 0.56f), new Vector3(1.48f, 0.78f, 0.76f), new Vector3(0, 8, 0), materials.wood) == null)
            {
                CreateBox("Creator Desk", root, new Vector3(-2.35f, 0.70f, 0.56f), new Vector3(1.42f, 0.13f, 0.74f), materials.wood);
                CreateBox("Desk Left Leg", root, new Vector3(-2.92f, 0.35f, 0.26f), new Vector3(0.08f, 0.70f, 0.08f), materials.blackMetal);
                CreateBox("Desk Right Leg", root, new Vector3(-1.78f, 0.35f, 0.86f), new Vector3(0.08f, 0.70f, 0.08f), materials.blackMetal);
            }

            PlaceKenneyAsset("Creator Chair", root, "chairDesk", new Vector3(-2.10f, 0.0f, -0.05f), new Vector3(0.42f, 0.82f, 0.42f), new Vector3(0, -166, 0), materials.sofa);
            PlaceKenneyAsset("Laptop Asset", root, "laptop", new Vector3(-2.54f, 0.80f, 0.48f), new Vector3(0.42f, 0.08f, 0.30f), new Vector3(0, 8, 0), materials.blackGlass);
            PlaceKenneyAsset("Computer Screen Asset", root, "computerScreen", new Vector3(-1.77f, 0.78f, 0.74f), new Vector3(0.42f, 0.36f, 0.12f), new Vector3(0, 188, 0), materials.blackGlass);
            PlaceKenneyAsset("Keyboard Asset", root, "computerKeyboard", new Vector3(-1.82f, 0.80f, 0.42f), new Vector3(0.42f, 0.035f, 0.14f), new Vector3(0, 8, 0), materials.blackGlass);
            PlaceKenneyAsset("Mouse Asset", root, "computerMouse", new Vector3(-1.44f, 0.80f, 0.42f), new Vector3(0.12f, 0.035f, 0.08f), new Vector3(0, 15, 0), materials.blackGlass);
            PlaceKenneyAsset("Desk Toy Bear", root, "bear", new Vector3(-3.05f, 0.80f, 0.46f), new Vector3(0.22f, 0.30f, 0.18f), new Vector3(0, -18, 0), materials.pillowWarm);
            CreateBox("Drawing Tablet", root, new Vector3(-2.42f, 0.80f, 0.52f), new Vector3(0.70f, 0.028f, 0.42f), materials.screen);
            CreateBox("Coffee Mug Desk", root, new Vector3(-2.92f, 0.84f, 0.78f), new Vector3(0.16f, 0.16f, 0.16f), materials.ceramic);
            if (PlaceKenneyAsset("Desk Lamp Asset", root, "lampRoundTable", new Vector3(-3.07f, 0.80f, 0.26f), new Vector3(0.28f, 0.52f, 0.28f), new Vector3(0, -22, 0), materials.lampShade) == null)
            {
                CreateCylinder("Desk Lamp Pole", root, new Vector3(-3.12f, 1.10f, 0.32f), new Vector3(0.025f, 0.36f, 0.025f), materials.blackMetal, Vector3.zero);
                CreateCylinder("Desk Lamp Head", root, new Vector3(-2.86f, 1.40f, 0.15f), new Vector3(0.17f, 0.08f, 0.17f), materials.lampShade, new Vector3(68, 0, 28));
            }
            AddLight("Desk Warm Practical", new Vector3(-2.80f, 1.33f, 0.22f), 1.1f, new Color(1.0f, 0.74f, 0.48f), 1.65f);
        }

        private static void CreateSofaZone(Transform root, SceneMaterials materials)
        {
            if (PlaceKenneyAsset("Sofa Model", root, "loungeDesignSofaCorner", new Vector3(2.22f, 0.0f, 0.78f), new Vector3(1.80f, 0.88f, 0.94f), new Vector3(0, 180, 0), materials.sofa) == null)
            {
                CreateBox("Sofa Base", root, new Vector3(2.22f, 0.36f, 0.78f), new Vector3(1.75f, 0.42f, 0.78f), materials.sofa);
                CreateBox("Sofa Back", root, new Vector3(2.22f, 0.75f, 1.08f), new Vector3(1.80f, 0.68f, 0.18f), materials.sofa);
            }

            PlaceKenneyAsset("Sofa Pillow A", root, "pillow", new Vector3(1.72f, 0.54f, 0.55f), new Vector3(0.38f, 0.16f, 0.18f), new Vector3(0, 18, 0), materials.pillowWarm);
            PlaceKenneyAsset("Sofa Pillow B", root, "pillowBlue", new Vector3(2.48f, 0.54f, 0.55f), new Vector3(0.42f, 0.16f, 0.18f), new Vector3(0, -12, 0), materials.pillowCool);
            PlaceKenneyAsset("Rug Model", root, "rugRectangle", new Vector3(0.55f, 0.0f, 0.62f), new Vector3(2.95f, 0.035f, 1.42f), new Vector3(0, 0, 0), materials.rug);
            if (PlaceKenneyAsset("Low Table Model", root, "tableCoffeeGlass", new Vector3(1.48f, 0.0f, -0.08f), new Vector3(0.92f, 0.34f, 0.52f), new Vector3(0, 12, 0), materials.wood) == null)
            {
                CreateCylinder("Low Table", root, new Vector3(1.48f, 0.30f, -0.08f), new Vector3(0.52f, 0.06f, 0.52f), materials.wood, Vector3.zero);
            }

            PlaceKenneyAsset("Floor Lamp Sofa", root, "lampRoundFloor", new Vector3(3.18f, 0.0f, 0.20f), new Vector3(0.34f, 1.55f, 0.34f), new Vector3(0, -26, 0), materials.lampShade);
            PlaceKenneyAsset("Speaker Shelf Detail", root, "speakerSmall", new Vector3(2.66f, 0.34f, -0.18f), new Vector3(0.16f, 0.18f, 0.14f), new Vector3(0, -20, 0), materials.blackMetal);
            CreateCylinder("Candle", root, new Vector3(1.25f, 0.42f, -0.20f), new Vector3(0.055f, 0.09f, 0.055f), materials.cityWarm, Vector3.zero);
        }

        private static void CreatePlantZone(Transform root, SceneMaterials materials)
        {
            PlaceKenneyAsset("Plant Pot Big Model", root, "pottedPlant", new Vector3(2.76f, 0.0f, -0.52f), new Vector3(0.64f, 0.88f, 0.64f), new Vector3(0, 18, 0), materials.leaf);
            CreateCylinder("Plant Pot Big Glow Base", root, new Vector3(2.76f, 0.03f, -0.52f), new Vector3(0.36f, 0.016f, 0.36f), materials.hexGlow, Vector3.zero);
            for (var i = 0; i < 9; i++)
            {
                var angle = i * 40.0f;
                var radians = angle * Mathf.Deg2Rad;
                var leaf = CreateSphere("Plant Leaf " + i, root, new Vector3(2.76f + Mathf.Cos(radians) * 0.25f, 0.60f + (i % 3) * 0.07f, -0.52f + Mathf.Sin(radians) * 0.18f), new Vector3(0.12f, 0.035f, 0.22f), materials.leaf);
                leaf.transform.localRotation = Quaternion.Euler(18, angle, 0);
            }

            PlaceKenneyAsset("Small Plant Model", root, "plantSmall2", new Vector3(0.58f, 1.02f, -1.04f), new Vector3(0.22f, 0.34f, 0.22f), new Vector3(0, -12, 0), materials.leaf);
            CreateCylinder("Small Plant Pot", root, new Vector3(0.58f, 1.08f, -1.04f), new Vector3(0.11f, 0.10f, 0.11f), materials.ceramicDark, Vector3.zero);
            CreateSphere("Small Plant Leaf A", root, new Vector3(0.52f, 1.22f, -1.04f), new Vector3(0.06f, 0.02f, 0.13f), materials.leaf);
            CreateSphere("Small Plant Leaf B", root, new Vector3(0.64f, 1.23f, -1.03f), new Vector3(0.06f, 0.02f, 0.13f), materials.leaf);
        }

        private static void CreateShelves(Transform root, SceneMaterials materials)
        {
            PlaceKenneyAsset("Bookcase Closed Wide", root, "bookcaseClosedWide", new Vector3(-3.08f, 0.0f, 2.05f), new Vector3(1.14f, 1.45f, 0.34f), new Vector3(0, 180, 0), materials.lightWood);
            PlaceKenneyAsset("Open Bookcase", root, "bookcaseOpen", new Vector3(3.18f, 0.0f, 1.86f), new Vector3(0.72f, 1.52f, 0.34f), new Vector3(0, 180, 0), materials.lightWood);

            for (var shelf = 0; shelf < 3; shelf++)
            {
                CreateBox("Shelf Board " + shelf, root, new Vector3(-3.08f, 1.20f + shelf * 0.34f, 2.16f), new Vector3(1.14f, 0.045f, 0.24f), materials.lightWood);
            }

            for (var i = 0; i < 15; i++)
            {
                var shelf = i / 5;
                var x = -3.52f + (i % 5) * 0.18f;
                var height = 0.18f + (i % 3) * 0.05f;
                CreateBox("Book " + i, root, new Vector3(x, 1.31f + shelf * 0.34f, 2.02f), new Vector3(0.055f, height, 0.11f), i % 2 == 0 ? materials.bookPink : materials.bookBlue);
            }

            PlaceKenneyAsset("Book Stack Island", root, "books", new Vector3(-0.88f, 1.04f, -0.42f), new Vector3(0.26f, 0.13f, 0.22f), new Vector3(0, 18, 0), materials.bookBlue);
            PlaceKenneyAsset("Radio Shelf Prop", root, "radio", new Vector3(-3.32f, 1.68f, 2.02f), new Vector3(0.20f, 0.16f, 0.12f), new Vector3(0, 180, 0), materials.blackGlass);
        }

        private static void CreateLighting(Transform root, SceneMaterials materials)
        {
            CreateCylinder("Pendant Cable A", root, new Vector3(-0.46f, 2.50f, -0.42f), new Vector3(0.012f, 0.28f, 0.012f), materials.blackMetal, Vector3.zero);
            CreateCylinder("Pendant Shade A", root, new Vector3(-0.46f, 2.22f, -0.42f), new Vector3(0.20f, 0.09f, 0.20f), materials.lampShade, Vector3.zero);
            CreateCylinder("Pendant Cable B", root, new Vector3(0.34f, 2.50f, -0.56f), new Vector3(0.012f, 0.24f, 0.012f), materials.blackMetal, Vector3.zero);
            CreateCylinder("Pendant Shade B", root, new Vector3(0.34f, 2.26f, -0.56f), new Vector3(0.16f, 0.08f, 0.16f), materials.lampShade, Vector3.zero);
            AddLight("Warm Pendant Key", new Vector3(-0.35f, 2.05f, -0.58f), 1.9f, new Color(1.0f, 0.69f, 0.42f), 3.8f);
            AddLight("Kitchen Warm Fill", new Vector3(0.35f, 1.75f, -0.80f), 1.25f, new Color(1.0f, 0.55f, 0.32f), 2.35f);
            AddLight("Window Cool Fill", new Vector3(2.35f, 1.70f, 1.15f), 1.45f, new Color(0.30f, 0.52f, 1.0f), 3.25f);
            AddLight("Neon Accent", new Vector3(-1.85f, 1.55f, 1.90f), 1.25f, new Color(0.16f, 0.95f, 0.85f), 2.8f);
            AddLight("Plant Scan Practical", new Vector3(2.50f, 0.88f, -0.46f), 0.85f, new Color(0.16f, 1.0f, 0.68f), 1.4f);
            AddLight("Sofa Candle Bounce", new Vector3(1.34f, 0.75f, -0.08f), 0.65f, new Color(1.0f, 0.55f, 0.25f), 1.2f);
        }

        private static void CreateDiegeticHud(Transform root, SceneMaterials materials)
        {
            CreateBox("Kitchen Status Plate", root, new Vector3(0.72f, 1.48f, 2.16f), new Vector3(0.54f, 0.22f, 0.024f), materials.panel);
            CreateWorldText("dinner prep", root, new Vector3(0.56f, 1.52f, 2.08f), 0.011f, materials.textGreen, "Kitchen Status Text", TextAnchor.MiddleLeft);
        }

        private static void CreateAstra(SoulForgeBridge bridge, SceneMaterials materials)
        {
            var root = new GameObject("Astra-F").transform;
            root.position = new Vector3(-2.34f, 0, 0.42f);
            root.rotation = Quaternion.Euler(0, 28, 0);

            var rig = new GameObject("Astra_Rig").transform;
            rig.SetParent(root, false);
            PlaceMiniCharacter("Astra Visible Character", rig, "character-female-a", new Vector3(0.0f, 0.0f, -0.12f), new Vector3(0.64f, 1.50f, 0.48f), new Vector3(0, 0, 0), materials.astraShell);

            var torso = CreateBox("Torso", rig, new Vector3(0, 1.03f, 0), new Vector3(0.36f, 0.62f, 0.20f), materials.astraShell);
            HideVisual(torso);
            HideVisual(CreateBox("Chest Control Glass", rig, new Vector3(0, 1.09f, -0.112f), new Vector3(0.24f, 0.22f, 0.016f), materials.screenPink));
            HideVisual(CreateSphere("Head", rig, new Vector3(0, 1.62f, 0), new Vector3(0.27f, 0.30f, 0.25f), materials.astraSkin));
            HideVisual(CreateBox("Face Visor", rig, new Vector3(0, 1.60f, -0.21f), new Vector3(0.26f, 0.08f, 0.025f), materials.blackGlass));
            HideVisual(CreateSphere("Hair Shell", rig, new Vector3(0, 1.75f, 0.02f), new Vector3(0.31f, 0.16f, 0.28f), materials.astraHair));
            HideVisual(CreateBox("Waist", rig, new Vector3(0, 0.70f, 0), new Vector3(0.30f, 0.18f, 0.17f), materials.blackMetal));

            var leftUpper = CreateArm(rig, "Left Arm", new Vector3(-0.28f, 1.30f, 0), 0.36f, 0.31f, 0.045f, materials.astraShell, 8);
            var rightUpper = CreateArm(rig, "Right Arm", new Vector3(0.28f, 1.30f, 0), 0.36f, 0.31f, 0.045f, materials.astraShell, -8);
            var leftForearm = FindChild(leftUpper, "Left Arm Forearm Pivot");
            var rightForearm = FindChild(rightUpper, "Right Arm Forearm Pivot");
            CreateLeg(rig, "Left Leg", new Vector3(-0.12f, 0.62f, 0), 0.40f, 0.40f, 0.052f, materials.astraShell);
            CreateLeg(rig, "Right Leg", new Vector3(0.12f, 0.62f, 0), 0.40f, 0.40f, 0.052f, materials.astraShell);

            var pencil = CreateBox("Stylus Prop", rightForearm, new Vector3(0.0f, -0.34f, -0.08f), new Vector3(0.025f, 0.22f, 0.025f), materials.neon);
            pencil.transform.localRotation = Quaternion.Euler(28, 0, 20);
            var glow = CreateSphere("Astra Activity Glow", rig, new Vector3(0, 0.08f, 0), new Vector3(0.42f, 0.018f, 0.42f), materials.astraGlow);
            CreateNameLabel("Astra-F\ncreative companion", rig, new Vector3(0, 1.98f, 0), materials.textPink);

            WireAgent(root.gameObject, "astra", bridge, rig, FindChild(rig, "Head"), leftUpper, rightUpper, leftForearm, rightForearm, null, pencil.transform, null, glow.transform);
        }

        private static void CreateMason(SoulForgeBridge bridge, SceneMaterials materials)
        {
            var root = new GameObject("Mason-M").transform;
            root.position = new Vector3(-0.18f, 0, -0.18f);
            root.rotation = Quaternion.Euler(0, -6, 0);

            var rig = new GameObject("Mason_Rig").transform;
            rig.SetParent(root, false);
            PlaceMiniCharacter("Mason Visible Character", rig, "character-male-f", new Vector3(0.0f, 0.0f, -0.12f), new Vector3(0.64f, 1.42f, 0.48f), new Vector3(0, 0, 0), materials.masonShell);

            HideVisual(CreateBox("Service Torso", rig, new Vector3(0, 1.05f, 0), new Vector3(0.50f, 0.68f, 0.26f), materials.masonShell));
            HideVisual(CreateBox("Apron Module", rig, new Vector3(0, 0.96f, -0.145f), new Vector3(0.42f, 0.42f, 0.018f), materials.fabricDark));
            HideVisual(CreateSphere("Head", rig, new Vector3(0, 1.70f, 0), new Vector3(0.26f, 0.26f, 0.24f), materials.masonSkin));
            HideVisual(CreateBox("Face Display", rig, new Vector3(0, 1.68f, -0.205f), new Vector3(0.28f, 0.09f, 0.024f), materials.screenBlue));
            HideVisual(CreateBox("Back Battery", rig, new Vector3(0, 1.05f, 0.18f), new Vector3(0.34f, 0.46f, 0.10f), materials.blackMetal));

            var leftUpper = CreateArm(rig, "Left Arm", new Vector3(-0.37f, 1.34f, 0), 0.40f, 0.34f, 0.060f, materials.masonShell, 6);
            var rightUpper = CreateArm(rig, "Right Arm", new Vector3(0.37f, 1.34f, 0), 0.40f, 0.34f, 0.060f, materials.masonShell, -6);
            var leftForearm = FindChild(leftUpper, "Left Arm Forearm Pivot");
            var rightForearm = FindChild(rightUpper, "Right Arm Forearm Pivot");
            CreateLeg(rig, "Left Heavy Leg", new Vector3(-0.16f, 0.64f, 0), 0.43f, 0.42f, 0.070f, materials.masonShell);
            CreateLeg(rig, "Right Heavy Leg", new Vector3(0.16f, 0.64f, 0), 0.43f, 0.42f, 0.070f, materials.masonShell);

            var spatula = CreateBox("Kitchen Tool Prop", rightForearm, new Vector3(0.0f, -0.36f, -0.10f), new Vector3(0.035f, 0.30f, 0.026f), materials.blackMetal);
            spatula.transform.localRotation = Quaternion.Euler(24, 0, -14);
            CreateBox("Tool Blade", spatula.transform, new Vector3(0, -0.18f, 0), new Vector3(0.13f, 0.045f, 0.018f), materials.counter);
            var glow = CreateSphere("Mason Activity Glow", rig, new Vector3(0, 0.08f, 0), new Vector3(0.48f, 0.018f, 0.48f), materials.masonGlow);
            CreateNameLabel("Mason-M\ncare and cook", rig, new Vector3(0, 2.06f, 0), materials.textBlue);

            WireAgent(root.gameObject, "mason", bridge, rig, FindChild(rig, "Head"), leftUpper, rightUpper, leftForearm, rightForearm, null, spatula.transform, null, glow.transform);
        }

        private static void CreateHex(SoulForgeBridge bridge, SceneMaterials materials)
        {
            var root = new GameObject("Hex-01").transform;
            root.position = new Vector3(1.24f, 0, -0.10f);
            root.rotation = Quaternion.Euler(0, -34, 0);

            var rig = new GameObject("Hex_Rig").transform;
            rig.SetParent(root, false);

            CreateSphere("Core Body", rig, new Vector3(0, 0.62f, 0), new Vector3(0.34f, 0.30f, 0.34f), materials.hexShell);
            CreateSphere("Sensor Head", rig, new Vector3(0, 1.02f, -0.02f), new Vector3(0.24f, 0.18f, 0.20f), materials.hexShell);
            CreateBox("Face Screen", rig, new Vector3(0, 1.02f, -0.19f), new Vector3(0.24f, 0.075f, 0.026f), materials.screenGreen);
            CreateSphere("Left Eye", rig, new Vector3(-0.07f, 1.025f, -0.214f), new Vector3(0.026f, 0.026f, 0.010f), materials.neon);
            CreateSphere("Right Eye", rig, new Vector3(0.07f, 1.025f, -0.214f), new Vector3(0.026f, 0.026f, 0.010f), materials.neon);

            var leftUpper = CreateArm(rig, "Left Utility Arm", new Vector3(-0.30f, 0.72f, 0), 0.25f, 0.20f, 0.040f, materials.hexShell, 18);
            var rightUpper = CreateArm(rig, "Right Utility Arm", new Vector3(0.30f, 0.72f, 0), 0.25f, 0.20f, 0.040f, materials.hexShell, -18);
            var leftForearm = FindChild(leftUpper, "Left Utility Arm Forearm Pivot");
            var rightForearm = FindChild(rightUpper, "Right Utility Arm Forearm Pivot");

            for (var i = 0; i < 4; i++)
            {
                var x = i < 2 ? -0.23f : 0.23f;
                var z = i % 2 == 0 ? -0.16f : 0.16f;
                CreateCylinder("Hex Leg " + i, rig, new Vector3(x, 0.30f, z), new Vector3(0.040f, 0.22f, 0.040f), materials.blackMetal, new Vector3(i % 2 == 0 ? 14 : -14, 0, 0));
                CreateSphere("Hex Foot " + i, rig, new Vector3(x, 0.08f, z), new Vector3(0.11f, 0.045f, 0.09f), materials.hexShell);
            }

            var scanBeam = CreateBox("Plant Scan Beam", rig, new Vector3(0.38f, 0.55f, -0.38f), new Vector3(0.38f, 0.46f, 0.035f), materials.scanBeam);
            scanBeam.transform.localRotation = Quaternion.Euler(0, -22, 0);
            var tool = CreateBox("Repair Driver Prop", rightForearm, new Vector3(0, -0.24f, -0.07f), new Vector3(0.030f, 0.22f, 0.030f), materials.blackMetal);
            tool.transform.localRotation = Quaternion.Euler(26, 0, -18);
            var glow = CreateSphere("Hex Activity Glow", rig, new Vector3(0, 0.05f, 0), new Vector3(0.54f, 0.018f, 0.54f), materials.hexGlow);
            CreateNameLabel("Hex-01\nnon-human scout", rig, new Vector3(0, 1.38f, 0), materials.textGreen);

            WireAgent(root.gameObject, "hex", bridge, rig, FindChild(rig, "Sensor Head"), leftUpper, rightUpper, leftForearm, rightForearm, null, tool.transform, scanBeam.transform, glow.transform);
        }

        private static Transform CreateArm(Transform parent, string name, Vector3 shoulder, float upperLength, float forearmLength, float radius, Material material, float restingRoll)
        {
            var upperPivot = new GameObject(name + " Upper Pivot").transform;
            upperPivot.SetParent(parent, false);
            upperPivot.localPosition = shoulder;
            upperPivot.localRotation = Quaternion.Euler(4, 0, restingRoll);

            CreateCylinder(name + " Upper Mesh", upperPivot, new Vector3(0, -upperLength * 0.5f, 0), new Vector3(radius, upperLength * 0.5f, radius), material, Vector3.zero);
            CreateSphere(name + " Elbow", upperPivot, new Vector3(0, -upperLength, 0), new Vector3(radius * 1.35f, radius * 1.35f, radius * 1.35f), material);

            var forearmPivot = new GameObject(name + " Forearm Pivot").transform;
            forearmPivot.SetParent(upperPivot, false);
            forearmPivot.localPosition = new Vector3(0, -upperLength, 0);
            forearmPivot.localRotation = Quaternion.Euler(-14, 0, 0);
            CreateCylinder(name + " Forearm Mesh", forearmPivot, new Vector3(0, -forearmLength * 0.5f, 0), new Vector3(radius * 0.88f, forearmLength * 0.5f, radius * 0.88f), material, Vector3.zero);
            CreateSphere(name + " Hand", forearmPivot, new Vector3(0, -forearmLength, -0.02f), new Vector3(radius * 1.45f, radius * 1.2f, radius * 1.45f), material);
            return upperPivot;
        }

        private static void CreateLeg(Transform parent, string name, Vector3 hip, float upperLength, float lowerLength, float radius, Material material)
        {
            CreateCylinder(name + " Thigh", parent, hip + new Vector3(0, -upperLength * 0.5f, 0), new Vector3(radius, upperLength * 0.5f, radius), material, Vector3.zero);
            CreateSphere(name + " Knee", parent, hip + new Vector3(0, -upperLength, 0), new Vector3(radius * 1.30f, radius * 1.30f, radius * 1.30f), material);
            CreateCylinder(name + " Shin", parent, hip + new Vector3(0, -upperLength - lowerLength * 0.5f, 0), new Vector3(radius * 0.92f, lowerLength * 0.5f, radius * 0.92f), material, Vector3.zero);
            CreateSphere(name + " Foot", parent, hip + new Vector3(0, -upperLength - lowerLength, -0.05f), new Vector3(radius * 1.75f, radius * 0.65f, radius * 2.20f), material);
        }

        private static void WireAgent(GameObject root, string id, SoulForgeBridge bridge, Transform bodyRoot, Transform head, Transform leftUpperArm, Transform rightUpperArm, Transform leftForearm, Transform rightForearm, Transform leftProp, Transform rightProp, Transform scanBeam, Transform activityLight)
        {
            var controller = root.AddComponent<SoulForgeAgentController>();
            SetString(controller, "agentId", id);
            SetObject(controller, "bridge", bridge);

            var procedural = root.AddComponent<SoulForgeProceduralAgentAnimator>();
            SetString(procedural, "agentId", id);
            SetObject(procedural, "bridge", bridge);
            SetObject(procedural, "bodyRoot", bodyRoot);
            SetObject(procedural, "head", head);
            SetObject(procedural, "leftUpperArm", leftUpperArm);
            SetObject(procedural, "rightUpperArm", rightUpperArm);
            SetObject(procedural, "leftForearm", leftForearm);
            SetObject(procedural, "rightForearm", rightForearm);
            SetObject(procedural, "leftHandProp", leftProp);
            SetObject(procedural, "rightHandProp", rightProp);
            SetObject(procedural, "scanBeam", scanBeam);
            SetObject(procedural, "activityLight", activityLight);
            SetObject(controller, "proceduralAnimator", procedural);
        }

        private static void CreateHud(SoulForgeBridge bridge)
        {
            var canvasObject = new GameObject("SoulForgeHUD");
            var canvas = canvasObject.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = Camera.main;
            canvas.planeDistance = 0.45f;
            canvasObject.AddComponent<CanvasScaler>();
            canvasObject.AddComponent<GraphicRaycaster>();

            CreateStaticHudOverlay(canvasObject.transform);

            var panel = new GameObject("DialoguePanel");
            panel.transform.SetParent(canvasObject.transform, false);
            var image = panel.AddComponent<Image>();
            image.color = new Color(0.02f, 0.025f, 0.035f, 0.84f);
            var rect = image.rectTransform;
            rect.anchorMin = new Vector2(0.24f, 0.025f);
            rect.anchorMax = new Vector2(0.83f, 0.17f);
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;

            var speaker = CreateText("Speaker", panel.transform, new Vector2(0.04f, 0.52f), new Vector2(0.22f, 0.92f), 26);
            var line = CreateText("Line", panel.transform, new Vector2(0.25f, 0.20f), new Vector2(0.94f, 0.72f), 22);
            var meta = CreateText("Meta", panel.transform, new Vector2(0.25f, 0.72f), new Vector2(0.94f, 0.94f), 13);

            var hud = canvasObject.AddComponent<SoulForgeDialogueHud>();
            SetObject(hud, "bridge", bridge);
            SetObject(hud, "speakerText", speaker);
            SetObject(hud, "dialogueText", line);
            SetObject(hud, "metaText", meta);
        }

        private static void CreateStaticHudOverlay(Transform canvas)
        {
            var timePanel = CreateHudPanel("TimePanel", canvas, new Vector2(0.012f, 0.80f), new Vector2(0.172f, 0.972f), new Color(0.018f, 0.024f, 0.035f, 0.86f));
            var timeText = CreateText("TimeText", timePanel.transform, new Vector2(0.10f, 0.66f), new Vector2(0.94f, 0.92f), 14);
            timeText.text = "Day 1  Tue";
            timeText.color = new Color(0.93f, 0.96f, 1.0f);
            var clockText = CreateText("ClockText", timePanel.transform, new Vector2(0.10f, 0.36f), new Vector2(0.94f, 0.66f), 28);
            clockText.text = "20:47";
            clockText.color = new Color(1.0f, 1.0f, 1.0f);
            var timeMeta = CreateText("TimeMeta", timePanel.transform, new Vector2(0.10f, 0.12f), new Vector2(0.94f, 0.34f), 12);
            timeMeta.text = "Evening  |  Dinner";
            timeMeta.color = new Color(0.62f, 0.74f, 0.92f);

            var schedulePanel = CreateHudPanel("SchedulePanel", canvas, new Vector2(0.014f, 0.34f), new Vector2(0.178f, 0.78f), new Color(0.012f, 0.016f, 0.026f, 0.62f));
            var schedule = CreateText("ScheduleText", schedulePanel.transform, new Vector2(0.10f, 0.04f), new Vector2(0.96f, 0.96f), 13);
            schedule.text = "07:00   Wake Up\n08:30   Morning Routine\n09:30   Work / Study\n12:30   Lunch Break\n14:00   Project Time\n17:30   Free Time\n19:00   Dinner  >\n20:00   Chat & Connect\n22:30   Wind Down\n23:30   Sleep";
            schedule.color = new Color(0.78f, 0.84f, 0.92f);

            var goalPanel = CreateHudPanel("GoalPanel", canvas, new Vector2(0.805f, 0.905f), new Vector2(0.986f, 0.972f), new Color(0.014f, 0.020f, 0.030f, 0.84f));
            var goal = CreateText("GoalText", goalPanel.transform, new Vector2(0.08f, 0.12f), new Vector2(0.95f, 0.88f), 13);
            goal.text = "Main Goal\nBuild wonderful memories together";
            goal.color = new Color(0.92f, 0.96f, 1.0f);

            var relationPanel = CreateHudPanel("RelationPanel", canvas, new Vector2(0.835f, 0.58f), new Vector2(0.973f, 0.81f), new Color(0.016f, 0.022f, 0.034f, 0.82f));
            var relation = CreateText("RelationText", relationPanel.transform, new Vector2(0.12f, 0.08f), new Vector2(0.96f, 0.92f), 13);
            relation.text = "Relations     Activity\n\nAstra-F        Creative   92\nMason-M        Cooking    86\nHex-01         Exploring  74";
            relation.color = new Color(0.82f, 0.92f, 1.0f);

            CreateCharacterCard(canvas, "Astra-F", "Creative", new Color(1.0f, 0.38f, 0.70f), new Vector2(0.012f, 0.022f), new Vector2(0.083f, 0.205f), "character-female-a.png");
            CreateCharacterCard(canvas, "Mason-M", "Care & Cook", new Color(0.36f, 0.67f, 1.0f), new Vector2(0.092f, 0.022f), new Vector2(0.163f, 0.205f), "character-male-f.png");
            CreateCharacterCard(canvas, "Hex-01", "AI Scout", new Color(0.38f, 1.0f, 0.72f), new Vector2(0.172f, 0.022f), new Vector2(0.233f, 0.205f), null);
        }

        private static Image CreateHudPanel(string name, Transform parent, Vector2 min, Vector2 max, Color color)
        {
            var panel = new GameObject(name);
            panel.transform.SetParent(parent, false);
            var image = panel.AddComponent<Image>();
            image.color = color;
            var rect = image.rectTransform;
            rect.anchorMin = min;
            rect.anchorMax = max;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
            return image;
        }

        private static void CreateCharacterCard(Transform canvas, string name, string role, Color accent, Vector2 min, Vector2 max, string portraitAsset)
        {
            var panel = CreateHudPanel(name + "Card", canvas, min, max, new Color(0.015f, 0.020f, 0.032f, 0.86f));
            var portrait = CreateHudPanel(name + "Portrait", panel.transform, new Vector2(0.12f, 0.34f), new Vector2(0.88f, 0.92f), new Color(accent.r * 0.55f, accent.g * 0.55f, accent.b * 0.55f, 0.72f));
            portrait.type = Image.Type.Simple;
            if (!string.IsNullOrEmpty(portraitAsset))
            {
                var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(KenneyMiniPreviewRoot + portraitAsset);
                if (texture != null)
                {
                    portrait.sprite = Sprite.Create(texture, new Rect(0, 0, texture.width, texture.height), new Vector2(0.5f, 0.5f));
                    portrait.preserveAspect = true;
                    portrait.color = Color.white;
                }
            }
            var label = CreateText(name + "CardText", panel.transform, new Vector2(0.10f, 0.05f), new Vector2(0.94f, 0.32f), 12);
            label.text = name + "\n" + role;
            label.color = accent;
        }

        private static Text CreateText(string name, Transform parent, Vector2 min, Vector2 max, int size)
        {
            var textObject = new GameObject(name);
            textObject.transform.SetParent(parent, false);
            var text = textObject.AddComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.color = Color.white;
            text.fontSize = size;
            text.alignment = TextAnchor.MiddleLeft;
            var rect = text.rectTransform;
            rect.anchorMin = min;
            rect.anchorMax = max;
            rect.offsetMin = Vector2.zero;
            rect.offsetMax = Vector2.zero;
            return text;
        }

        private static TextMesh CreateWorldText(string content, Transform parent, Vector3 position, float size, Material material, string name, TextAnchor anchor = TextAnchor.MiddleCenter)
        {
            var textObject = new GameObject(name);
            textObject.transform.SetParent(parent, false);
            textObject.transform.localPosition = position;
            textObject.transform.localRotation = Quaternion.identity;
            var text = textObject.AddComponent<TextMesh>();
            text.text = content;
            text.anchor = anchor;
            text.alignment = TextAlignment.Left;
            text.characterSize = size;
            text.fontSize = 56;
            text.color = material.color;
            return text;
        }

        private static void CreateNameLabel(string content, Transform parent, Vector3 position, Material material)
        {
            CreateWorldText(content, parent, position, 0.011f, material, "Name Label");
        }

        private static void HideVisual(GameObject root)
        {
            if (root == null)
            {
                return;
            }

            foreach (var renderer in root.GetComponentsInChildren<Renderer>(true))
            {
                renderer.enabled = false;
            }
        }

        private static GameObject PlaceKenneyAsset(string name, Transform parent, string assetName, Vector3 footprintCenter, Vector3 targetSize, Vector3 euler, Material fallbackMaterial)
        {
            return PlacePrefabAsset(name, parent, KenneyFurnitureRoot + assetName + ".fbx", footprintCenter, targetSize, euler, fallbackMaterial, false);
        }

        private static GameObject PlaceMiniCharacter(string name, Transform parent, string assetName, Vector3 footprintCenter, Vector3 targetSize, Vector3 euler, Material fallbackMaterial)
        {
            return PlacePrefabAsset(name, parent, KenneyMiniCharacterRoot + assetName + ".obj", footprintCenter, targetSize, euler, fallbackMaterial, false);
        }

        private static GameObject PlaceKenneyCharacter(string name, Transform parent, string skinName, Vector3 footprintCenter, Vector3 targetSize, Vector3 euler, Color tint)
        {
            var material = CreateTexturedMaterial(name + "_Material", KenneyCharacterSkinRoot + skinName + ".png", tint);
            return PlacePrefabAsset(name, parent, KenneyCharacterModel, footprintCenter, targetSize, euler, material, true);
        }

        private static GameObject PlacePrefabAsset(string name, Transform parent, string assetPath, Vector3 footprintCenter, Vector3 targetSize, Vector3 euler, Material fallbackMaterial, bool forceMaterial)
        {
            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
            if (prefab == null)
            {
                return null;
            }

            var instance = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (instance == null)
            {
                return null;
            }

            instance.name = name;
            instance.transform.SetParent(parent, false);
            instance.transform.localPosition = Vector3.zero;
            instance.transform.localRotation = Quaternion.Euler(euler);
            instance.transform.localScale = Vector3.one;

            foreach (var collider in instance.GetComponentsInChildren<Collider>(true))
            {
                Object.DestroyImmediate(collider);
            }

            foreach (var renderer in instance.GetComponentsInChildren<Renderer>(true))
            {
                if (forceMaterial && fallbackMaterial != null)
                {
                    var materials = renderer.sharedMaterials;
                    for (var i = 0; i < materials.Length; i++)
                    {
                        materials[i] = fallbackMaterial;
                    }
                    renderer.sharedMaterials = materials;
                }
                else if (renderer.sharedMaterial == null && fallbackMaterial != null)
                {
                    renderer.sharedMaterial = fallbackMaterial;
                }
            }

            var bounds = CalculateBounds(instance);
            if (bounds.HasValue)
            {
                var size = bounds.Value.size;
                var scale = new Vector3(
                    AxisScale(targetSize.x, size.x),
                    AxisScale(targetSize.y, size.y),
                    AxisScale(targetSize.z, size.z)
                );
                instance.transform.localScale = Vector3.Scale(instance.transform.localScale, scale);
            }

            var placedBounds = CalculateBounds(instance);
            if (placedBounds.HasValue)
            {
                var boundsValue = placedBounds.Value;
                var desiredWorld = parent == null ? footprintCenter : parent.TransformPoint(footprintCenter);
                instance.transform.position += new Vector3(
                    desiredWorld.x - boundsValue.center.x,
                    desiredWorld.y - boundsValue.min.y,
                    desiredWorld.z - boundsValue.center.z
                );
            }

            return instance;
        }

        private static Material CreateTexturedMaterial(string name, string texturePath, Color tint)
        {
            var material = CreateMaterial(name, tint, 0.0f, 0.46f);
            var texture = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath);
            if (texture != null)
            {
                if (material.HasProperty("_MainTex"))
                {
                    material.SetTexture("_MainTex", texture);
                }
                if (material.HasProperty("_BaseMap"))
                {
                    material.SetTexture("_BaseMap", texture);
                }
            }

            return material;
        }

        private static float AxisScale(float target, float source)
        {
            if (target <= 0.001f || source <= 0.001f)
            {
                return 1.0f;
            }

            return target / source;
        }

        private static Bounds? CalculateBounds(GameObject root)
        {
            var renderers = root.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
            {
                return null;
            }

            var bounds = renderers[0].bounds;
            for (var i = 1; i < renderers.Length; i++)
            {
                bounds.Encapsulate(renderers[i].bounds);
            }

            return bounds;
        }

        private static GameObject CreateBox(string name, Transform parent, Vector3 position, Vector3 scale, Material material)
        {
            return CreatePrimitive(name, parent, PrimitiveType.Cube, position, scale, material, Vector3.zero);
        }

        private static GameObject CreateSphere(string name, Transform parent, Vector3 position, Vector3 scale, Material material)
        {
            return CreatePrimitive(name, parent, PrimitiveType.Sphere, position, scale, material, Vector3.zero);
        }

        private static GameObject CreateCylinder(string name, Transform parent, Vector3 position, Vector3 scale, Material material, Vector3 euler)
        {
            return CreatePrimitive(name, parent, PrimitiveType.Cylinder, position, scale, material, euler);
        }

        private static GameObject CreatePrimitive(string name, Transform parent, PrimitiveType type, Vector3 position, Vector3 scale, Material material, Vector3 euler)
        {
            var primitive = GameObject.CreatePrimitive(type);
            primitive.name = name;
            primitive.transform.SetParent(parent, false);
            primitive.transform.localPosition = position;
            primitive.transform.localScale = scale;
            primitive.transform.localRotation = Quaternion.Euler(euler);
            var renderer = primitive.GetComponent<Renderer>();
            if (renderer != null)
            {
                renderer.sharedMaterial = material;
            }

            var collider = primitive.GetComponent<Collider>();
            if (collider != null)
            {
                Object.DestroyImmediate(collider);
            }

            return primitive;
        }

        private static void AddLight(string name, Vector3 position, float intensity, Color color, float range)
        {
            var lightObject = new GameObject(name);
            lightObject.transform.position = position;
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.intensity = intensity;
            light.color = color;
            light.range = range;
            light.shadows = LightShadows.Soft;
            light.shadowStrength = 0.48f;
            light.shadowBias = 0.04f;
        }

        private static Material CreateMaterial(string name, Color color, float metallic = 0.0f, float smoothness = 0.45f, bool emission = false)
        {
            var shader = Shader.Find("Standard");
            if (shader == null)
            {
                shader = Shader.Find("Universal Render Pipeline/Lit");
            }
            if (shader == null)
            {
                shader = Shader.Find("Sprites/Default");
            }

            var material = new Material(shader);
            material.name = name;
            material.color = color;
            if (material.HasProperty("_Color"))
            {
                material.SetColor("_Color", color);
            }
            if (material.HasProperty("_Metallic"))
            {
                material.SetFloat("_Metallic", metallic);
            }
            if (material.HasProperty("_Glossiness"))
            {
                material.SetFloat("_Glossiness", smoothness);
            }
            if (emission && material.HasProperty("_EmissionColor"))
            {
                material.EnableKeyword("_EMISSION");
                material.SetColor("_EmissionColor", color * 1.8f);
            }

            return material;
        }

        private static Material CreateTransparentMaterial(string name, Color color, float alpha)
        {
            color.a = alpha;
            var material = CreateMaterial(name, color, 0.0f, 0.35f, true);
            if (material.HasProperty("_Mode"))
            {
                material.SetFloat("_Mode", 3.0f);
                material.SetInt("_SrcBlend", (int)UnityEngine.Rendering.BlendMode.SrcAlpha);
                material.SetInt("_DstBlend", (int)UnityEngine.Rendering.BlendMode.OneMinusSrcAlpha);
                material.SetInt("_ZWrite", 0);
                material.DisableKeyword("_ALPHATEST_ON");
                material.EnableKeyword("_ALPHABLEND_ON");
                material.DisableKeyword("_ALPHAPREMULTIPLY_ON");
                material.renderQueue = 3000;
            }

            return material;
        }

        private static SceneMaterials CreateMaterials()
        {
            return new SceneMaterials
            {
                wall = CreateMaterial("SF_Wall_Charcoal", new Color(0.075f, 0.085f, 0.105f), 0.0f, 0.18f),
                ceiling = CreateMaterial("SF_Ceiling_SoftGrey", new Color(0.46f, 0.51f, 0.49f), 0.0f, 0.20f),
                floor = CreateMaterial("SF_WoodFloor", new Color(0.33f, 0.23f, 0.15f), 0.0f, 0.40f),
                floorLine = CreateMaterial("SF_FloorLine", new Color(0.20f, 0.14f, 0.10f), 0.0f, 0.30f),
                wood = CreateMaterial("SF_WarmWood", new Color(0.48f, 0.30f, 0.20f), 0.0f, 0.38f),
                lightWood = CreateMaterial("SF_LightWood", new Color(0.62f, 0.43f, 0.28f), 0.0f, 0.36f),
                counter = CreateMaterial("SF_Countertop", new Color(0.62f, 0.53f, 0.46f), 0.0f, 0.55f),
                cabinet = CreateMaterial("SF_Cabinet", new Color(0.06f, 0.09f, 0.12f), 0.0f, 0.35f),
                fridge = CreateMaterial("SF_Fridge_Matte", new Color(0.16f, 0.19f, 0.21f), 0.3f, 0.50f),
                blackMetal = CreateMaterial("SF_BlackMetal", new Color(0.035f, 0.040f, 0.045f), 0.55f, 0.60f),
                blackGlass = CreateMaterial("SF_BlackGlass", new Color(0.015f, 0.020f, 0.026f), 0.0f, 0.82f),
                window = CreateTransparentMaterial("SF_NightWindow", new Color(0.02f, 0.11f, 0.22f), 0.74f),
                cityWarm = CreateMaterial("SF_CityWarm", new Color(1.0f, 0.66f, 0.25f), 0.0f, 0.55f, true),
                cityCool = CreateMaterial("SF_CityCool", new Color(0.22f, 0.58f, 1.0f), 0.0f, 0.55f, true),
                neon = CreateMaterial("SF_TealNeon", new Color(0.08f, 0.88f, 0.75f), 0.0f, 0.85f, true),
                screen = CreateMaterial("SF_TabletScreen", new Color(0.10f, 0.26f, 0.42f), 0.0f, 0.82f, true),
                screenPink = CreateMaterial("SF_PinkScreen", new Color(1.0f, 0.34f, 0.70f), 0.0f, 0.82f, true),
                screenBlue = CreateMaterial("SF_BlueScreen", new Color(0.18f, 0.55f, 1.0f), 0.0f, 0.82f, true),
                screenGreen = CreateMaterial("SF_GreenScreen", new Color(0.18f, 1.0f, 0.75f), 0.0f, 0.82f, true),
                ceramic = CreateMaterial("SF_Ceramic", new Color(0.86f, 0.82f, 0.76f), 0.0f, 0.55f),
                ceramicDark = CreateMaterial("SF_CeramicDark", new Color(0.22f, 0.20f, 0.18f), 0.0f, 0.45f),
                leaf = CreateMaterial("SF_Leaf", new Color(0.14f, 0.44f, 0.25f), 0.0f, 0.36f),
                red = CreateMaterial("SF_RedProp", new Color(0.86f, 0.16f, 0.10f), 0.0f, 0.35f),
                sofa = CreateMaterial("SF_Sofa_Teal", new Color(0.17f, 0.30f, 0.34f), 0.0f, 0.38f),
                pillowWarm = CreateMaterial("SF_PillowWarm", new Color(0.76f, 0.47f, 0.30f), 0.0f, 0.42f),
                pillowCool = CreateMaterial("SF_PillowCool", new Color(0.22f, 0.42f, 0.62f), 0.0f, 0.42f),
                rug = CreateMaterial("SF_Rug", new Color(0.36f, 0.18f, 0.16f), 0.0f, 0.34f),
                lampShade = CreateMaterial("SF_LampShade", new Color(0.86f, 0.62f, 0.38f), 0.0f, 0.48f),
                panel = CreateTransparentMaterial("SF_HUDPanel", new Color(0.02f, 0.035f, 0.055f), 0.82f),
                textPink = CreateMaterial("SF_TextPink", new Color(1.0f, 0.46f, 0.75f), 0.0f, 0.45f, true),
                textBlue = CreateMaterial("SF_TextBlue", new Color(0.42f, 0.72f, 1.0f), 0.0f, 0.45f, true),
                textGreen = CreateMaterial("SF_TextGreen", new Color(0.40f, 1.0f, 0.72f), 0.0f, 0.45f, true),
                pink = CreateMaterial("SF_PinkNote", new Color(0.92f, 0.32f, 0.54f), 0.0f, 0.35f),
                bookPink = CreateMaterial("SF_BookPink", new Color(0.72f, 0.28f, 0.45f), 0.0f, 0.30f),
                bookBlue = CreateMaterial("SF_BookBlue", new Color(0.22f, 0.38f, 0.62f), 0.0f, 0.30f),
                fabricDark = CreateMaterial("SF_FabricDark", new Color(0.06f, 0.07f, 0.085f), 0.0f, 0.45f),
                astraShell = CreateMaterial("SF_AstraShell", new Color(0.88f, 0.56f, 0.72f), 0.2f, 0.58f),
                astraSkin = CreateMaterial("SF_AstraFace", new Color(0.96f, 0.74f, 0.72f), 0.0f, 0.54f),
                astraHair = CreateMaterial("SF_AstraHair", new Color(0.88f, 0.42f, 0.66f), 0.0f, 0.48f),
                masonShell = CreateMaterial("SF_MasonShell", new Color(0.25f, 0.48f, 0.78f), 0.25f, 0.60f),
                masonSkin = CreateMaterial("SF_MasonFace", new Color(0.36f, 0.40f, 0.46f), 0.15f, 0.55f),
                hexShell = CreateMaterial("SF_HexShell", new Color(0.26f, 0.78f, 0.70f), 0.25f, 0.62f),
                astraGlow = CreateTransparentMaterial("SF_AstraGlow", new Color(1.0f, 0.35f, 0.66f), 0.36f),
                masonGlow = CreateTransparentMaterial("SF_MasonGlow", new Color(0.22f, 0.56f, 1.0f), 0.32f),
                hexGlow = CreateTransparentMaterial("SF_HexGlow", new Color(0.14f, 1.0f, 0.76f), 0.36f),
                scanBeam = CreateTransparentMaterial("SF_ScanBeam", new Color(0.20f, 1.0f, 0.65f), 0.28f)
            };
        }

        private static Transform FindChild(Transform root, string name)
        {
            foreach (Transform child in root.GetComponentsInChildren<Transform>(true))
            {
                if (child.name == name)
                {
                    return child;
                }
            }

            return null;
        }

        private static Vector3 ShotPosition(string shot)
        {
            switch (shot)
            {
                case "coffee": return new Vector3(-2.86f, 1.22f, -2.74f);
                case "kitchen": return new Vector3(-0.88f, 1.30f, -3.42f);
                case "plant": return new Vector3(1.72f, 1.18f, -2.86f);
                case "conversation": return new Vector3(-0.36f, 1.26f, -3.32f);
                case "sketch": return new Vector3(-2.94f, 1.16f, -2.38f);
                case "desk": return new Vector3(-2.15f, 1.18f, -2.72f);
                case "repair": return new Vector3(1.82f, 1.05f, -2.64f);
                case "dance": return new Vector3(-0.52f, 1.36f, -3.62f);
                case "sofa": return new Vector3(2.16f, 1.10f, -2.72f);
                default: return new Vector3(-1.20f, 1.32f, -4.05f);
            }
        }

        private static Vector3 ShotLookAt(string shot)
        {
            switch (shot)
            {
                case "coffee": return new Vector3(-2.18f, 0.96f, 0.38f);
                case "kitchen": return new Vector3(-0.28f, 0.98f, -0.80f);
                case "plant": return new Vector3(1.64f, 0.72f, -0.30f);
                case "conversation": return new Vector3(-0.50f, 1.02f, -0.26f);
                case "sketch": return new Vector3(-2.24f, 0.95f, 0.42f);
                case "desk": return new Vector3(-1.34f, 0.96f, 0.36f);
                case "repair": return new Vector3(1.18f, 0.66f, -0.12f);
                case "dance": return new Vector3(-0.58f, 0.95f, -0.50f);
                case "sofa": return new Vector3(1.70f, 0.74f, 0.62f);
                default: return new Vector3(-0.04f, 0.94f, 0.08f);
            }
        }

        private static void SetString(Object target, string property, string value)
        {
            var serialized = new SerializedObject(target);
            serialized.FindProperty(property).stringValue = value;
            serialized.ApplyModifiedProperties();
        }

        private static void SetObject(Object target, string property, Object value)
        {
            var serialized = new SerializedObject(target);
            serialized.FindProperty(property).objectReferenceValue = value;
            serialized.ApplyModifiedProperties();
        }

        private static void SetShots(SoulForgeTimelineDirector director, Transform[] shotAnchors)
        {
            var serialized = new SerializedObject(director);
            var shots = serialized.FindProperty("shots");
            shots.arraySize = shotAnchors.Length;
            for (var i = 0; i < shotAnchors.Length; i++)
            {
                var item = shots.GetArrayElementAtIndex(i);
                item.FindPropertyRelative("name").stringValue = ShotNames[i];
                item.FindPropertyRelative("anchor").objectReferenceValue = shotAnchors[i];
            }
            serialized.ApplyModifiedProperties();
        }

        private sealed class SceneMaterials
        {
            public Material wall;
            public Material ceiling;
            public Material floor;
            public Material floorLine;
            public Material wood;
            public Material lightWood;
            public Material counter;
            public Material cabinet;
            public Material fridge;
            public Material blackMetal;
            public Material blackGlass;
            public Material window;
            public Material cityWarm;
            public Material cityCool;
            public Material neon;
            public Material screen;
            public Material screenPink;
            public Material screenBlue;
            public Material screenGreen;
            public Material ceramic;
            public Material ceramicDark;
            public Material leaf;
            public Material red;
            public Material sofa;
            public Material pillowWarm;
            public Material pillowCool;
            public Material rug;
            public Material lampShade;
            public Material panel;
            public Material textPink;
            public Material textBlue;
            public Material textGreen;
            public Material pink;
            public Material bookPink;
            public Material bookBlue;
            public Material fabricDark;
            public Material astraShell;
            public Material astraSkin;
            public Material astraHair;
            public Material masonShell;
            public Material masonSkin;
            public Material hexShell;
            public Material astraGlow;
            public Material masonGlow;
            public Material hexGlow;
            public Material scanBeam;
        }
    }
}
#endif
