
import React, { useState, useEffect } from "react";
import axios from "axios";

const baseURL = "http://localhost:5000";

function App() {
  const [url, setUrl] = useState("");
  const [info, setInfo] = useState(null);
  const [downloadId, setDownloadId] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [downloadingFormat, setDownloadingFormat] = useState(null);
  const [errorMsg, setErrorMsg] = useState(null);
  const [activeTab, setActiveTab] = useState("video");
  const [progress, setProgress] = useState(0);
  const [stopPolling, setStopPolling] = useState(false);

  // Polling for progress
  useEffect(() => {
    if (!downloadId) return;
    const intervalId = setInterval(async () => {
      try {
        const res = await axios.get(`${baseURL}/api/progress/${downloadId}`);
        setProgress(res.data.progress || 0);
      } catch {
        setProgress(0);
      }
    }, 1000);
    return () => clearInterval(intervalId);
  }, [downloadId]);

  // ✅ Request cookies from Chrome Extension
  // inside App.js
// ✅ NEW - using content script bridge
const handleAllowCookies = () => {
  return new Promise((resolve) => {
    // 1. Listen for the response from content.js
    const listener = (event) => {
      if (event.data.type === "COOKIES_RESPONSE") {
        window.removeEventListener("message", listener);
        resolve(event.data.data); // response from background.js
      }
    };
    window.addEventListener("message", listener);

    // 2. Ask content.js to fetch cookies
    window.postMessage({ type: "GET_COOKIES" }, "*");
  });
};

const fetchCookies = async () => {
  const response = await handleAllowCookies();
  if (response?.success) {
    console.log("✅ Cookies from extension:", response.cookies);

    await axios.post(`${baseURL}/api/upload-cookies`, {
      user_id: "chanakya_user",
      cookies: response.cookies,
    });

    alert("✅ Cookies sent to Flask successfully!");
  } else {
    alert("❌ Failed to fetch cookies");
  }
};

  const handleCheckInfo = async () => {
    setAnalyzing(true);
    setInfo(null);
    setErrorMsg(null);
    try {
      const res = await axios.post(`${baseURL}/api/info`, { url });
      setInfo(res.data);
    } catch {
      setErrorMsg("❌ Failed to fetch video info. Please check the URL.");
    } finally {
      setAnalyzing(false);
    }
  };

  const handleCancelDownload = async () => {
    if (!downloadId) return;
    setStopPolling(true);
    try {
      await axios.post(`${baseURL}/api/cancel/${downloadId}`);
      setErrorMsg("✅ Download cancelled.");
    } catch {
      setErrorMsg("⚠️ Failed to cancel download.");
    }
    resetDownloadState();
  };

  const resetDownloadState = () => {
    setDownloadingFormat(null);
    setDownloadId(null);
    setProgress(0);
    setStopPolling(false);
  };

  const pollForFileDownload = async (jobId, ext) => {
    const maxRetries = 30;
    const interval = 2000;

    for (let i = 0; i < maxRetries; i++) {
      if (stopPolling) return;

      try {
        const res = await axios.get(`${baseURL}/api/download-file/${jobId}`, {
          responseType: "blob",
          validateStatus: () => true,
        });

        if (stopPolling) return;

        if (res.status === 200 && res.data.size > 1000) {
          const blob = new Blob([res.data], { type: res.headers["content-type"] });
          const downloadUrl = window.URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = downloadUrl;
          a.download = `ChanakyaMusic_${(info?.title || "youtube_download").replace(/[\\/:*?"<>|]/g, "")}.${ext || "mp4"}`;
          document.body.appendChild(a);
          a.click();
          a.remove();
          return;
        }

        if (res.status === 400) {
          setErrorMsg("❌ Download was cancelled.");
          return;
        }
      } catch {}
      await new Promise((res) => setTimeout(res, interval));
    }

    setErrorMsg("⚠️ Download timed out or failed.");
  };

  const handleFormatDownload = async (format) => {
    resetDownloadState();
    setDownloadingFormat(format);
    setStopPolling(false);
    setErrorMsg(null);

    try {
      const res = await axios.post(`${baseURL}/api/download`, {
        url,
        selected_format: format,
        title: info?.title || "youtube_download",
      });

      const jobId = res.data.job_id;
      setDownloadId(jobId);
      await pollForFileDownload(jobId, format.ext);
    } catch {
      setErrorMsg("❌ Download failed to start.");
    } finally {
      resetDownloadState();
    }
  };

  const formatDuration = (seconds) => {
    if (!seconds || isNaN(seconds)) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs < 10 ? "0" : ""}${secs}`;
  };

  const formatFileSize = (mb) =>
    !mb || isNaN(mb) ? "-" : mb > 1024 ? `${(mb / 1024).toFixed(2)} GB` : `${mb.toFixed(2)} MB`;

  const filteredFormats = (type) =>
    info?.formats
      ?.filter((f) =>
        type === "video" ? !f.audio_only && f.ext === "mp4" : f.audio_only && f.ext === "mp3"
      )
      .sort((a, b) => {
        if (a.requires_merge !== b.requires_merge) return a.requires_merge ? 1 : -1;
        return (b.resolution || 0) - (a.resolution || 0);
      }) || [];

  return (
    <div style={styles.container}>
      <style>
        {`
          @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
          html, body { background-color: #121212; margin: 0; padding: 0; }
          progress::-webkit-progress-bar { background-color: #444; border-radius: 8px; }
          progress::-webkit-progress-value { background-color: #28a745; border-radius: 8px; }
          progress::-moz-progress-bar { background-color: #28a745; border-radius: 8px; }
        `}
      </style>

      <h1 style={styles.title}>Chanakya Musical World 🎵</h1>

      {/* ✅ Allow Cookies Button */}
      <div style={{ marginBottom: "15px" }}>
        <button 
  onClick={fetchCookies} 
  style={{ ...styles.analyzeBtn, backgroundColor: "#28a745" }}
>
  ✅ Allow (Fetch Cookies)
</button>

      </div>

      {/* Input */}
      <div style={styles.inputSection}>
        <input
          type="text"
          placeholder="Paste YouTube URL here..."
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          style={styles.input}
        />
        <button
          onClick={handleCheckInfo}
          disabled={analyzing}
          style={{
            ...styles.analyzeBtn,
            backgroundColor: analyzing ? "#888" : "#007bff",
            cursor: analyzing ? "not-allowed" : "pointer",
          }}
        >
          {analyzing ? "⏳ Analyzing..." : "🔍 Analyze"}
        </button>
      </div>

      {/* Results */}
      {analyzing ? (
        <div style={styles.resultBox}>
          <div style={styles.spinner}></div>
          <p style={styles.loadingText}>🔄 Fetching video info, please wait...</p>
        </div>
      ) : info ? (
        <div style={styles.resultBox}>
          <img src={info.thumbnail} alt="Thumbnail" style={styles.thumbnail} />
          <h2>{info.title}</h2>
          <p><strong>Duration:</strong> {formatDuration(info.duration)}</p>

          {/* Tabs */}
          <div style={styles.tabSection}>
            <button
              style={{ ...styles.tab, backgroundColor: activeTab === "video" ? "#28a745" : "black" }}
              onClick={() => setActiveTab("video")}
            >
              🎥 Video
            </button>
            <button
              style={{ ...styles.tab, backgroundColor: activeTab === "audio" ? "#28a745" : "black" }}
              onClick={() => setActiveTab("audio")}
            >
              🎵 Audio
            </button>
          </div>

          {/* Formats */}
          <div style={styles.formatList}>
            {filteredFormats(activeTab).map((f) => {
              const isDownloadingThis = downloadingFormat?.format_id === f.format_id;
              const isDownloading = downloadingFormat !== null;

              return (
                <div
                  key={f.format_id}
                  style={{
                    ...styles.formatItem,
                    opacity: !isDownloadingThis && isDownloading ? 0.5 : 1,
                    cursor: isDownloading && !isDownloadingThis ? "not-allowed" : "pointer",
                  }}
                  onClick={() => {
                    if (!isDownloading) handleFormatDownload(f);
                  }}
                >
                  <div>
                    <strong>{f.ext.toUpperCase()}</strong> -{" "}
                    {f.audio_only ? `${f.abr || "???"} kbps Audio` : `${f.resolution || "?"}p Video`}
                    <div style={{ fontSize: 14, color: "#999", marginTop: 6 }}>
                      Size: {formatFileSize(f.filesize)}
                    </div>
                  </div>

                  <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "center" }}>
                    {isDownloadingThis ? (
                      <>
                        <progress value={progress} max="100" style={styles.progressBar}></progress>
                        <span style={styles.progressText}>⬇️ {progress}%</span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCancelDownload();
                          }}
                          style={{ ...styles.selectBtn, backgroundColor: "red" }}
                        >
                          ❌ Cancel
                        </button>
                      </>
                    ) : (
                      <button style={{ ...styles.selectBtn, backgroundColor: "#28a745" }}>
                        {isDownloading ? "Please wait..." : "Click to Download"}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div style={styles.welcomeBox}>
          <h2>👋 Welcome to Chanakya Downloader</h2>
          <p>Paste a YouTube URL above and click <strong>Analyze</strong> to begin your download!</p>
        </div>
      )}

      {errorMsg && <p style={styles.error}>{errorMsg}</p>}
    </div>
  );
}

const styles = {
  container: {
    maxWidth: "1500px",
    margin: "auto",
    padding: "30px 20px",
    fontFamily: "'Inter', 'Roboto', sans-serif",
    textAlign: "center",
    backgroundColor: "#121212",
    minHeight: "100vh",
    color: "#e0e0e0",
  },
  title: { fontSize: "32px", marginBottom: "20px", color: "#ffffff" },
  inputSection: { display: "flex", gap: "10px", justifyContent: "center", marginBottom: "20px" },
  input: {
    padding: "12px", fontSize: "16px", borderRadius: "8px", border: "1px solid #444",
    width: "60%", backgroundColor: "#1e1e1e", color: "#fff"
  },
  analyzeBtn: {
    padding: "12px 20px", borderRadius: "8px", backgroundColor: "#007bff",
    color: "white", border: "none", transition: "background 0.3s ease"
  },
  resultBox: {
    backgroundColor: "#1e1e1e", padding: "24px", borderRadius: "12px",
    marginTop: "20px", boxShadow: "0 4px 12px rgba(255, 255, 255, 0.05)"
  },
  welcomeBox: {
    backgroundColor: "#1e1e1e", padding: "24px", borderRadius: "12px",
    marginTop: "20px", color: "#ccc", fontSize: "16px"
  },
  spinner: {
    width: "40px", height: "40px", margin: "auto", border: "4px solid #444",
    borderTop: "4px solid #28a745", borderRadius: "50%",
    animation: "spin 1s linear infinite"
  },
  loadingText: { marginTop: "15px", fontSize: "16px", color: "#ccc" },
  thumbnail: { width: "380px", borderRadius: "10px", marginBottom: "15px" },
  tabSection: { display: "flex", justifyContent: "center", margin: "20px 0" },
  tab: {
    padding: "10px 20px", margin: "0 6px", color: "#fff", border: "none",
    borderRadius: "8px", cursor: "pointer", backgroundColor: "#333"
  },
  formatList: { display: "flex", flexDirection: "column", gap: "12px", marginTop: "20px" },
  formatItem: {
    display: "flex", justifyContent: "space-between", padding: "16px", gap: "12px",
    border: "1px solid #333", borderRadius: "10px", alignItems: "center",
    backgroundColor: "#2c2c2c", boxShadow: "0 2px 6px rgba(0,0,0,0.5)"
  },
  selectBtn: {
    padding: "8px 16px", border: "none", borderRadius: "6px",
    color: "white", fontSize: "14px"
  },
  progressBar: { width: "160px", height: "14px", borderRadius: "8px", backgroundColor: "#444" },
  progressText: { fontSize: "13px", marginTop: "4px", color: "#ccc" },
  error: { color: "#ff6b6b", marginTop: "16px", fontWeight: "bold" },
};

export default App;
