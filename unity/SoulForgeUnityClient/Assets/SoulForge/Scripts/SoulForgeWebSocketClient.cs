using System;
using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using UnityEngine;

namespace SoulForge.UnityClient
{
    public class SoulForgeWebSocketClient : MonoBehaviour
    {
        [SerializeField] private SoulForgeBridge bridge;
        [SerializeField] private string websocketUrl = "ws://127.0.0.1:8080/ws";
        [SerializeField] private bool connectOnStart;

        private readonly ConcurrentQueue<string> pendingMessages = new ConcurrentQueue<string>();
        private ClientWebSocket socket;
        private CancellationTokenSource cancellation;

        private async void Start()
        {
            if (connectOnStart)
            {
                await Connect();
            }
        }

        private void Update()
        {
            while (pendingMessages.TryDequeue(out var json))
            {
                if (bridge != null)
                {
                    bridge.PublishJson(json);
                }
            }
        }

        private async void OnDisable()
        {
            await Disconnect();
        }

        public async Task Connect()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            Debug.LogWarning("System.Net.WebSockets is not available for WebGL builds. Use a WebGL websocket package for browser deployment.");
            await Task.CompletedTask;
#else
            if (socket != null && socket.State == WebSocketState.Open)
            {
                return;
            }

            cancellation = new CancellationTokenSource();
            socket = new ClientWebSocket();
            await socket.ConnectAsync(new Uri(websocketUrl), cancellation.Token);
            _ = ReceiveLoop(cancellation.Token);
#endif
        }

        public async Task Disconnect()
        {
#if UNITY_WEBGL && !UNITY_EDITOR
            await Task.CompletedTask;
#else
            if (cancellation != null)
            {
                cancellation.Cancel();
            }

            if (socket != null && socket.State == WebSocketState.Open)
            {
                await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "SoulForge client closing", CancellationToken.None);
            }

            socket?.Dispose();
            socket = null;
            cancellation?.Dispose();
            cancellation = null;
#endif
        }

#if !UNITY_WEBGL || UNITY_EDITOR
        private async Task ReceiveLoop(CancellationToken token)
        {
            var buffer = new byte[8192];
            while (!token.IsCancellationRequested && socket != null && socket.State == WebSocketState.Open)
            {
                var builder = new StringBuilder();
                WebSocketReceiveResult result;
                do
                {
                    result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), token);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        return;
                    }

                    builder.Append(Encoding.UTF8.GetString(buffer, 0, result.Count));
                } while (!result.EndOfMessage);

                pendingMessages.Enqueue(builder.ToString());
            }
        }
#endif
    }
}
