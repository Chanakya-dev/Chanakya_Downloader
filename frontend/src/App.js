import React, { useState, useEffect } from "react";
import axios from "axios";

const baseURL = "https://server-download-fxza.onrender.com";

function LoginPage({ onCookiesUploaded, errorMsg, uploadingCookies }) {
  const handleCookieFileUpload = async (e) => {
    onCookiesUploaded(e);
  };

  return (
    <div style={styles.container}>
      <h1 style={styles.title}>Chanakya Musical World 🎵</h1>
      <div style={styles.welcomeBox}>
        <h2>Upload YouTube Cookies</h2>
        <p>
          To download restricted videos, install the{" "}
          <a
            href="https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "#007bff" }}
          >
            Get cookies.txt LOCALLY
          </a>{" "}
          Chrome extension, export your YouTube cookies, and upload the cookies.txt file here.{" "}
          <a
            href="https://your-frontend-domain.com/cookie-guide"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: "#007bff" }}
          >
            Learn how to export cookies
          </a>.
        </p>
        <input
          type="file"
          accept=".txt"
          onChange={handleCookieFileUpload}
          disabled={uploadingCookies}
          style={styles.input}
        />
        <button
          onClick={() => document.querySelector('input[type="file"]').click()}
          style={{ ...styles.analyzeBtn, backgroundColor: "#28a745", marginTop: "10px" }}
          disabled={uploadingCookies}
        >
          {uploadingCookies ? "⏳ Uploading..." : "📂 Upload Cookies"}
        </button>
        {errorMsg && <p style={styles.error}>{errorMsg}</p>}
      </div>
    </div>
  );
}

function MainApp({ url, setUrl, info, setInfo, downloadId, setDownloadId, analyzing, setAnalyzing, downloadingFormat, setDownloadingFormat, errorMsg, setErrorMsg, activeTab, setActiveTab, progress, setProgress, stopPolling, setStopPolling, userId, setHasCookies }) {
  const handleCheckInfo = async () => {
    setAnalyzing(true);
    setInfo(null);
    setErrorMsg(null);
    try {
      const res = await axios.post(`${baseURL}/api/info`, { url, user_id: userId });
      setInfo(res.data);
    } catch (error) {
      const errorMsg = error.response?.data?.error || "❌ Failed to fetch video info. Please check the URL.";
      setErrorMsg(errorMsg);
      if (error.response?.status === 401) {
        setHasCookies(false);
      }
    } finally {
      setAnalyzing(false);
    }
  };

  const testCookies = async () => {
    setErrorMsg(null);
    try {
      const res = await axios.post(`${baseURL}/api/test-cookies`, {
        user_id: userId,
        test_url: "https://www.youtube.com/watch?v=restricted_video_id", // Replace with a known restricted video ID
      });
      alert(`✅ Cookie test successful: ${res.data.title}`);
    } catch (error) {
      const errorMsg = error.response?.data?.error || "Failed to test cookies. Please try again.";
      setErrorMsg(errorMsg);
      if (error.response?.status === 401) {
        setHasCookies(false);
        alert("⚠️ Cookies invalid or expired. Please re-upload a valid cookies.txt file.");
      }
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
        if (res.status === 401) {
          setHasCookies(false);
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
        user_id: userId
      });
      const jobId = res.data.job_id;
      setDownloadId(jobId);
      await pollForFileDownload(jobId, format.ext);
    } catch (error) {
      setErrorMsg("❌ Download failed to start.");
      if (error.response?.status === 401) {
        setHasCookies(false);
      }
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
      <h1 style={styles.title}>Chanakya Musical World 🎵</h1>
      <div style={{ marginBottom: "15px" }}>
        <button
          onClick={testCookies}
          style={{ ...styles.analyzeBtn, backgroundColor: "#007bff" }}
        >
          🔍 Test Cookies
        </button>
      </div>
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
  const [hasCookies, setHasCookies] = useState(null);
  const [uploadingCookies, setUploadingCookies] = useState(false);

  const getUserId = () => {
    let userId = localStorage.getItem("userId");
    if (!userId) {
      userId = crypto.randomUUID();
      localStorage.setItem("userId", userId);
    }
    return userId;
  };

  const userId = getUserId();

  useEffect(() => {
    const checkCookies = async () => {
      try {
        const res = await axios.post(`${baseURL}/api/has-cookies`, { user_id: userId });
        setHasCookies(res.data.has_cookies);
      } catch {
        setHasCookies(false);
      }
    };
    checkCookies();
  }, [userId]);

  useEffect(() => {
    if (!downloadId || stopPolling) return;
    const intervalId = setInterval(async () => {
      try {
        const res = await axios.get(`${baseURL}/api/progress/${downloadId}`);
        setProgress(res.data.progress || 0);
      } catch {
        setProgress(0);
      }
    }, 1000);
    return () => clearInterval(intervalId);
  }, [downloadId, stopPolling]);

  const handleCookieFileUpload = async (e) => {
    setUploadingCookies(true);
    setErrorMsg(null);
    const file = e.target.files[0];
    if (!file) {
      setErrorMsg("❌ No file selected. Please upload a cookies.txt file.");
      setUploadingCookies(false);
      return;
    }

    try {
      const formData = new FormData();
      formData.append("user_id", userId);
      formData.append("cookies_file", file);
      await axios.post(`${baseURL}/api/upload-cookies`, formData, {
        headers: { "Content-Type": "multipart/form-data" }
      });
      setHasCookies(true);
      alert("✅ Cookies uploaded successfully! Please test cookies to verify.");
    } catch (error) {
      setErrorMsg(
        `❌ Failed to upload cookies: ${error.response?.data?.error || "Unknown error"}`
      );
      setHasCookies(false);
    } finally {
      setUploadingCookies(false);
    }
  };

  if (hasCookies === null) {
    return (
      <div style={styles.container}>
        <h1 style={styles.title}>Chanakya Musical World 🎵</h1>
        <p>Loading...</p>
      </div>
    );
  }

  return hasCookies ? (
    <MainApp
      url={url}
      setUrl={setUrl}
      info={info}
      setInfo={setInfo}
      downloadId={downloadId}
      setDownloadId={setDownloadId}
      analyzing={analyzing}
      setAnalyzing={setAnalyzing}
      downloadingFormat={downloadingFormat}
      setDownloadingFormat={setDownloadingFormat}
      errorMsg={errorMsg}
      setErrorMsg={setErrorMsg}
      activeTab={activeTab}
      setActiveTab={setActiveTab}
      progress={progress}
      setProgress={setProgress}
      stopPolling={stopPolling}
      setStopPolling={setStopPolling}
      userId={userId}
      setHasCookies={setHasCookies}
    />
  ) : (
    <LoginPage
      onCookiesUploaded={handleCookieFileUpload}
      errorMsg={errorMsg}
      uploadingCookies={uploadingCookies}
    />
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