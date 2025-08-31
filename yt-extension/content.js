// Listen for messages from React app
window.addEventListener("message", (event) => {
  if (event.source !== window) return;

  if (event.data.type === "GET_COOKIES") {
    console.log("📩 Content script received request from React");

    chrome.runtime.sendMessage({ action: "getCookies" }, (res) => {
      console.log("📤 Content script got response:", res);

      window.postMessage(
        { type: "COOKIES_RESPONSE", data: res },
        "*"
      );
    });
  }
});
