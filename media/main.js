const input = document.getElementById('user-input');
const sendBtn = document.getElementById('send-btn');
const messages = document.getElementById('chat-messages');
const vscodeApi = acquireVsCodeApi();

let starterRemoved = false;

function getEditorContext() {
  return new Promise((resolve) => {
    vscodeApi.postMessage({ command: 'getContext' });

    window.addEventListener('message', function handleMsg(event) {
      const msg = event.data;
      if (msg.type === 'context') {
        window.removeEventListener('message', handleMsg);
        resolve(msg.data);
      }
    });
  });
}

function lockInput(shouldLock) {
  input.disabled = shouldLock;
  sendBtn.disabled = shouldLock;
  input.style.opacity = shouldLock ? '0.5' : '1';
  sendBtn.style.opacity = shouldLock ? '0.5' : '1';
  input.style.cursor = shouldLock ? 'not-allowed' : 'text';
  sendBtn.style.cursor = shouldLock ? 'not-allowed' : 'pointer';
}

function renderMarkdown(text) {
  // Escape HTML tags first (prevents XSS injection before formatting)
  text = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Ordered lists
  text = text.replace(/(^\s*\d+\.\s+.*(?:\r?\n(?:(?!\d+\.).+|\s*\d+\.\s+.*))*)/gm, function(match) {
    const lines = match.trim().split(/\r?\n/);
    let items = [];
    let currentItem = '';

    lines.forEach(line => {
      if (/^\s*\d+\.\s+/.test(line)) {
        if (currentItem) items.push(`<li>${currentItem}</li>`);
        currentItem = line.replace(/^\s*\d+\.\s+(.*)/, '$1');
      } else {
        currentItem += `<br>${line.trim()}`;
      }
    });

    if (currentItem) items.push(`<li>${currentItem}</li>`);
    return `<ol>${items.join('')}</ol>`;
  });

  // Unordered lists
  text = text.replace(/(^\s*[-*]\s+.*(?:\r?\n\s*[-*]\s+.*)*)/gm, function(match) {
    const items = match.trim().split(/\r?\n/).map(line =>
      line.replace(/^\s*[-*]\s+(.*)/, '<li>$1</li>')
    ).join('');
    return `<ul>${items}</ul>`;
  });

  // Headings, blockquotes, emphasis, links, etc.
  return text
    .replace(/^### (.*)$/gm, '<h3>$1</h3>')
    .replace(/^## (.*)$/gm, '<h2>$1</h2>')
    .replace(/^# (.*)$/gm, '<h1>$1</h1>')
    .replace(/^> (.*)$/gm, '<blockquote>$1</blockquote>')
    .replace(/^---$/gm, '<hr>')
    .replace(/```([\s\S]+?)```/g, '<pre><code>$1</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    .replace(/_(.+?)_/g, '<em>$1</em>')
    .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank">$1</a>');
}

function createMessageWrapper(msgEl) {
  const wrapper = document.createElement('div');
  wrapper.style.display = 'flex';
  wrapper.style.flexDirection = 'column';
  wrapper.style.alignItems = msgEl.classList.contains('user-message') ? 'flex-end' : 'flex-start';
  return wrapper;
}

function getThreadId() {
  const threadEl = document.querySelector('.thread-id');
  if (!threadEl) return 'unknown';
  return threadEl.textContent.replace('Thread: #', '').trim();
}

function addMessage(text, sender) {
  if (!starterRemoved) {
    const starter = document.querySelector('.starter-message');
    if (starter) starter.remove();
    starterRemoved = true;
  }

  const msg = document.createElement('div');
  msg.className = sender === 'user' ? 'user-message' : 'bot-message';
  const copyStatus = document.createElement('div');
  copyStatus.className = 'copy-status';
  copyStatus.textContent = 'Copied!';
  copyStatus.style.display = 'none';

  const wrapper = createMessageWrapper(msg);
  wrapper.appendChild(msg);
  wrapper.appendChild(copyStatus);
  messages.appendChild(wrapper);

  if (sender === 'bot') {
    msg.classList.add('clickable-bot');
    msg.innerHTML = renderMarkdown(text);
    msg.addEventListener('click', () => {
      navigator.clipboard.writeText(msg.textContent).then(() => {
        copyStatus.style.display = 'block';
        setTimeout(() => (copyStatus.style.display = 'none'), 1200);
      });
    });
  } else {
    msg.textContent = text;
  }

  requestAnimationFrame(() => {
    messages.scrollTop = messages.scrollHeight;
  });
}


async function sendMessage() {
  const text = input.value.trim();
  if (!text || sendBtn.disabled || input.disabled) return;

  addMessage(text, "user");
  input.value = "";
  input.style.height = "auto";
  lockInput(true);

  const context = await getEditorContext();
  const prompt = `${text}\nContext:\n${context}`;
  const threadId = getThreadId();

  try {
    const res = await fetch("http://localhost:8000/get_response", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, thread_id: threadId }),
    });

    if (!res.ok || !res.body) {
      throw new Error("Network error");
    }

    const botMsg = document.createElement("div");
    botMsg.className = "bot-message clickable-bot";
    botMsg.innerHTML = 'Sage is thinking<span class="dots"></span>';

    const copyStatus = document.createElement("div");
    copyStatus.className = "copy-status";
    copyStatus.textContent = "Copied!";
    copyStatus.style.display = "none";

    const wrapper = createMessageWrapper(botMsg);
    wrapper.appendChild(botMsg);
    wrapper.appendChild(copyStatus);
    messages.appendChild(wrapper);
    requestAnimationFrame(() => {
      messages.scrollTop = messages.scrollHeight;
    });

    botMsg.addEventListener("click", () => {
      navigator.clipboard.writeText(botMsg.textContent).then(() => {
        copyStatus.style.display = "block";
        setTimeout(() => (copyStatus.style.display = "none"), 1200);
      });
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullText = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });

      if (chunk.includes("[DONE]")) {
        botMsg.innerHTML = renderMarkdown(fullText);
        break;
      } else if (chunk.startsWith("[ERROR]")) {
        botMsg.innerHTML += `<br><em>Error: ${chunk.slice(7)}</em>`;
        break;
      } else {
        if (botMsg.querySelector('.dots')) {
          fullText = "";
          botMsg.innerHTML = "";
        }
        fullText += chunk;
        botMsg.innerHTML = renderMarkdown(fullText);

        requestAnimationFrame(() => {
          messages.scrollTop = messages.scrollHeight;
        });
      }
    }
  } catch (err) {
    addMessage("Something went wrong. Please try again.", "bot");
    console.error(err);
  } finally {
    lockInput(false);
  }
}



function changeThread() {
  const threadEl = document.querySelector('.thread-id');
  const inputBox = document.createElement('input');
  inputBox.type = 'text';
  inputBox.value = threadEl.textContent.replace('Thread: #', '');
  inputBox.className = 'thread-input';

  inputBox.addEventListener('blur', () => {
    threadEl.textContent = `Thread: #${inputBox.value || 'unknown'}`;
    threadEl.style.display = 'inline-block';
    inputBox.remove();
  });

  threadEl.style.display = 'none';
  threadEl.parentElement.appendChild(inputBox);
  inputBox.focus();
}

sendBtn.addEventListener('click', () => sendMessage());
input.addEventListener('keypress', (e) => {
  if (e.key === 'Enter') sendMessage();
});
input.addEventListener('input', () => {
  input.style.height = 'auto';
  input.style.height = input.scrollHeight + 'px';
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    sendMessage();
  }
});