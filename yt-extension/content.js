// Listen to messages from React app (DOM)
window.addEventListener("message", (event) => {
  if (event.source !== window) return; // only accept self messages

  if (event.data.type === "GET_COOKIES") {
    console.log("📩 Content script received request from React");

    chrome.runtime.sendMessage({ action: "getCookies" }, (res) => {
      console.log("📤 Content script got response:", res);

      // Send response back to React
      window.postMessage(
        { type: "COOKIES_RESPONSE", data: res },
        "*"
      );
    });
  }
});
