// SETUP REQUIRED:
// 1. Attach this script to any GameObject in your scene.
// 2. Install Newtonsoft.Json via Unity Package Manager:
//    Window > Package Manager > + > "Add package by name" > com.unity.nuget.newtonsoft-json

using System;
using System.Collections;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using Newtonsoft.Json;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

public class Client : MonoBehaviour
{
    [Header("Connection")]
    public string serverUrl = "http://localhost:5000";
    public int unityListenPort = 8080;
    public string coordinatorId = "coordinator";

    // Background HTTP listener (receives events from Python server)
    private HttpListener _listener;
    private Thread _listenerThread;

    // Work items from the listener thread that need to run on Unity's main thread
    private ConcurrentQueue<(Func<string> work, Action<string> callback)> _workQueue
        = new ConcurrentQueue<(Func<string>, Action<string>)>();

    // Track spawned GameObjects by server-assigned ID
    private Dictionary<string, GameObject> _objects = new Dictionary<string, GameObject>();

    // UI references
    private InputField _inputField;
    private Text _statusText;
    private Button _buildButton;

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    void Start()
    {
        CreateUI();
        StartHttpListener();
        Debug.Log("[Client] Ready. Server: " + serverUrl);
    }

    void Update()
    {
        // Drain the work queue — Unity API calls MUST happen on the main thread.
        while (_workQueue.TryDequeue(out var item))
        {
            string result = item.work();
            item.callback(result);
        }
    }

    void OnDestroy()
    {
        _listener?.Stop();
        _listenerThread?.Abort();
    }

    // ── HTTP Listener (background thread) ────────────────────────────────────

    void StartHttpListener()
    {
        _listener = new HttpListener();
        _listener.Prefixes.Add($"http://localhost:{unityListenPort}/");
        _listener.Start();

        _listenerThread = new Thread(() =>
        {
            while (_listener.IsListening)
            {
                try
                {
                    var ctx = _listener.GetContext();
                    // Handle each request on a thread pool thread so we don't block
                    ThreadPool.QueueUserWorkItem(_ => HandleRequest(ctx));
                }
                catch { /* listener was stopped */ }
            }
        });
        _listenerThread.IsBackground = true;
        _listenerThread.Start();

        Debug.Log($"[Client] Listening for Unity events on port {unityListenPort}");
    }

    void HandleRequest(HttpListenerContext ctx)
    {
        var req = ctx.Request;
        var res = ctx.Response;
        string responseBody = "ok";

        if (req.Url.AbsolutePath == "/event" && req.HttpMethod == "POST")
        {
            // Read the JSON body
            string json;
            using (var reader = new StreamReader(req.InputStream, req.ContentEncoding))
                json = reader.ReadToEnd();

            EventPayload payload;
            try { payload = JsonConvert.DeserializeObject<EventPayload>(json); }
            catch (Exception e) { responseBody = "bad json: " + e.Message; payload = null; }

            if (payload != null)
            {
                // Dispatch to main thread and wait for the result
                var done = new ManualResetEventSlim(false);
                _workQueue.Enqueue(
                    (() => DispatchEvent(payload),
                     result => { responseBody = result; done.Set(); })
                );
                done.Wait(5000); // wait up to 5 seconds
            }
        }

        byte[] bytes = Encoding.UTF8.GetBytes(responseBody);
        res.ContentType = "text/plain";
        res.ContentLength64 = bytes.Length;
        res.OutputStream.Write(bytes, 0, bytes.Length);
        res.Close();
    }

    // ── Event Dispatcher (main thread) ────────────────────────────────────────

    string DispatchEvent(EventPayload p)
    {
        Debug.Log($"[Client] Event: {p.eventName} id={p.id}");
        return p.eventName switch
        {
            "spawn_object"  => SpawnObject(p),
            "move_object"   => MoveObject(p),
            "draw_line"     => DrawLine(p),
            "delete_object" => DeleteObject(p),
            _               => $"unknown event: {p.eventName}",
        };
    }

    // ── Unity Event Handlers ──────────────────────────────────────────────────

    string SpawnObject(EventPayload p)
    {
        PrimitiveType primitive = p.type?.ToLower() switch
        {
            "sphere"   => PrimitiveType.Sphere,
            "cylinder" => PrimitiveType.Cylinder,
            "capsule"  => PrimitiveType.Capsule,
            _          => PrimitiveType.Cube,   // default to cube
        };

        var go = GameObject.CreatePrimitive(primitive);
        go.name = p.id;
        go.transform.position   = new Vector3(p.x, p.y, p.z);
        go.transform.localScale = new Vector3(p.sx, p.sy, p.sz);

        // Apply color (URP-compatible)
        var renderer = go.GetComponent<Renderer>();
        renderer.material = new Material(Shader.Find("Universal Render Pipeline/Lit"));
        renderer.material.color = new Color(p.r, p.g, p.b);

        _objects[p.id] = go;
        Debug.Log($"[Client] Spawned {p.type} '{p.id}' at ({p.x},{p.y},{p.z}) scale ({p.sx},{p.sy},{p.sz})");
        return "ok";
    }

    string MoveObject(EventPayload p)
    {
        if (!_objects.TryGetValue(p.id, out var go))
            return $"not found: {p.id}";

        go.transform.position = new Vector3(p.x, p.y, p.z);
        return "ok";
    }

    string DrawLine(EventPayload p)
    {
        var go = new GameObject("line_" + p.id);
        var lr = go.AddComponent<LineRenderer>();

        lr.positionCount = 2;
        lr.SetPosition(0, new Vector3(p.x, p.y, p.z));
        lr.SetPosition(1, new Vector3(p.ex, p.ey, p.ez));

        lr.startWidth = lr.endWidth = 0.05f;
        lr.material = new Material(Shader.Find("Sprites/Default"));
        lr.startColor = lr.endColor = new Color(p.r, p.g, p.b);
        lr.useWorldSpace = true;

        _objects[p.id] = go;
        return "ok";
    }

    string DeleteObject(EventPayload p)
    {
        if (!_objects.TryGetValue(p.id, out var go))
            return $"not found: {p.id}";

        Destroy(go);
        _objects.Remove(p.id);
        return "ok";
    }

    // ── Send instruction to coordinator ───────────────────────────────────────

    void OnBuildClicked()
    {
        string instruction = _inputField.text.Trim();
        if (string.IsNullOrEmpty(instruction)) return;

        _buildButton.interactable = false;
        _inputField.interactable = false;
        _statusText.text = "Working... (this may take a few minutes)";

        StartCoroutine(RunCoordinator(instruction));
    }

    IEnumerator RunCoordinator(string instruction)
    {
        string url = $"{serverUrl}/agents/{coordinatorId}/run";
        string body = JsonConvert.SerializeObject(new { instruction });
        byte[] bytes = Encoding.UTF8.GetBytes(body);

        using var req = new UnityWebRequest(url, "POST");
        req.uploadHandler   = new UploadHandlerRaw(bytes);
        req.downloadHandler = new DownloadHandlerBuffer();
        req.SetRequestHeader("Content-Type", "application/json");

        yield return req.SendWebRequest();

        _buildButton.interactable = true;
        _inputField.interactable  = true;

        if (req.result == UnityWebRequest.Result.Success)
        {
            _statusText.text = "Done!";
            Debug.Log("[Client] Coordinator finished: " + req.downloadHandler.text);
        }
        else
        {
            _statusText.text = "Error: " + req.error;
            Debug.LogError("[Client] Request failed: " + req.error);
        }
    }

    // ── UI (created programmatically — no prefabs needed) ─────────────────────

    void CreateUI()
    {
        // Canvas
        var canvasGo = new GameObject("AgentCanvas");
        var canvas = canvasGo.AddComponent<Canvas>();
        canvas.renderMode = RenderMode.ScreenSpaceOverlay;
        canvas.sortingOrder = 10;

        var scaler = canvasGo.AddComponent<CanvasScaler>();
        scaler.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        scaler.referenceResolution = new Vector2(1920, 1080);

        canvasGo.AddComponent<GraphicRaycaster>();

        // Bottom panel
        var panelGo = new GameObject("Panel");
        panelGo.transform.SetParent(canvas.transform, false);
        var panelImg = panelGo.AddComponent<Image>();
        panelImg.color = new Color(0.05f, 0.05f, 0.05f, 0.85f);

        var panelRt = panelGo.GetComponent<RectTransform>();
        panelRt.anchorMin = new Vector2(0, 0);
        panelRt.anchorMax = new Vector2(1, 0);
        panelRt.pivot     = new Vector2(0.5f, 0);
        panelRt.offsetMin = Vector2.zero;
        panelRt.offsetMax = new Vector2(0, 70);

        // Input field
        _inputField = CreateInputField(panelGo.transform);

        // Build button
        _buildButton = CreateButton(panelGo.transform, "Build");
        _buildButton.onClick.AddListener(OnBuildClicked);

        // Status text (above the panel)
        _statusText = CreateLabel(canvas.transform, "");
        var statusRt = _statusText.GetComponent<RectTransform>();
        statusRt.anchorMin        = new Vector2(0, 0);
        statusRt.anchorMax        = new Vector2(1, 0);
        statusRt.pivot            = new Vector2(0.5f, 0);
        statusRt.anchoredPosition = new Vector2(0, 75);
        statusRt.sizeDelta        = new Vector2(0, 25);
        _statusText.alignment     = TextAnchor.MiddleCenter;
        _statusText.color         = new Color(1f, 0.85f, 0.3f);
    }

    InputField CreateInputField(Transform parent)
    {
        var go = new GameObject("InputField");
        go.transform.SetParent(parent, false);

        var bg = go.AddComponent<Image>();
        bg.color = new Color(1, 1, 1, 0.95f);

        var field = go.AddComponent<InputField>();
        var rt = go.GetComponent<RectTransform>();
        rt.anchorMin        = new Vector2(0, 0.5f);
        rt.anchorMax        = new Vector2(1, 0.5f);
        rt.pivot            = new Vector2(0.5f, 0.5f);
        rt.offsetMin        = new Vector2(10, -22);
        rt.offsetMax        = new Vector2(-120, 22);

        // Text child
        var textGo  = new GameObject("Text");
        textGo.transform.SetParent(go.transform, false);
        var text    = textGo.AddComponent<Text>();
        text.font   = Font.CreateDynamicFontFromOSFont("Arial", 18);
        text.color  = Color.black;
        text.fontSize = 18;
        StretchRect(textGo.GetComponent<RectTransform>(), new Vector2(6, 4), new Vector2(-6, -4));
        field.textComponent = text;

        // Placeholder child
        var phGo  = new GameObject("Placeholder");
        phGo.transform.SetParent(go.transform, false);
        var ph    = phGo.AddComponent<Text>();
        ph.font   = Font.CreateDynamicFontFromOSFont("Arial", 18);
        ph.color  = new Color(0.5f, 0.5f, 0.5f, 0.8f);
        ph.fontStyle = FontStyle.Italic;
        ph.fontSize = 18;
        ph.text   = "Describe a building (e.g. 'a small medieval tower')...";
        StretchRect(phGo.GetComponent<RectTransform>(), new Vector2(6, 4), new Vector2(-6, -4));
        field.placeholder = ph;

        return field;
    }

    Button CreateButton(Transform parent, string label)
    {
        var go = new GameObject("Button_" + label);
        go.transform.SetParent(parent, false);

        var img  = go.AddComponent<Image>();
        img.color = new Color(0.15f, 0.55f, 1f);

        var btn = go.AddComponent<Button>();
        var colors = btn.colors;
        colors.highlightedColor = new Color(0.25f, 0.65f, 1f);
        colors.pressedColor     = new Color(0.05f, 0.4f, 0.9f);
        btn.colors = colors;

        var rt = go.GetComponent<RectTransform>();
        rt.anchorMin        = new Vector2(1, 0.5f);
        rt.anchorMax        = new Vector2(1, 0.5f);
        rt.pivot            = new Vector2(1, 0.5f);
        rt.anchoredPosition = new Vector2(-10, 0);
        rt.sizeDelta        = new Vector2(100, 44);

        var textGo = new GameObject("Text");
        textGo.transform.SetParent(go.transform, false);
        var text   = textGo.AddComponent<Text>();
        text.font  = Font.CreateDynamicFontFromOSFont("Arial", 18);
        text.color = Color.white;
        text.fontSize  = 18;
        text.fontStyle = FontStyle.Bold;
        text.alignment = TextAnchor.MiddleCenter;
        text.text      = label;
        StretchRect(textGo.GetComponent<RectTransform>(), Vector2.zero, Vector2.zero);

        return btn;
    }

    Text CreateLabel(Transform parent, string content)
    {
        var go  = new GameObject("Label");
        go.transform.SetParent(parent, false);
        var t   = go.AddComponent<Text>();
        t.font  = Font.CreateDynamicFontFromOSFont("Arial", 15);
        t.text  = content;
        t.fontSize = 15;
        return t;
    }

    // Set a RectTransform to stretch to parent with given offsets
    void StretchRect(RectTransform rt, Vector2 offsetMin, Vector2 offsetMax)
    {
        rt.anchorMin  = Vector2.zero;
        rt.anchorMax  = Vector2.one;
        rt.offsetMin  = offsetMin;
        rt.offsetMax  = offsetMax;
    }

    // ── Data model ────────────────────────────────────────────────────────────

    // Flat payload — server always sends all fields so no field is ever missing.
    class EventPayload
    {
        public string eventName;   // which event to handle
        public string id;          // object/line ID
        public string type;        // primitive type (cube, sphere, …) or "line"

        // Position (also line start for draw_line)
        public float x, y, z;

        // Line end point
        public float ex, ey, ez;

        // Scale
        public float sx = 1f, sy = 1f, sz = 1f;

        // Color
        public float r = 1f, g = 1f, b = 1f;
    }
}
