
const $ = (id) => document.getElementById(id);

// Communicate with the Flask backend.
async function api(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.message || `Request failed (${response.status})`);
  }

  return data;
}

// Display a message inside a panel.
function showMessage(container, message) {
  container.replaceChildren();
  container.classList.add("empty");

  const p = document.createElement("p");
  p.textContent = message;
  container.appendChild(p);
}

// Display a result card safely.
function addResult(container, title, description) {
  const card = document.createElement("div");
  card.className = "result-item";

  const heading = document.createElement("strong");
  heading.textContent = title;

  const detail = document.createElement("p");
  detail.textContent = description;

  card.append(heading, detail);
  container.appendChild(card);
  container.classList.remove("empty");
}

// Check the Flask backend.
async function checkHealth() {
  const status = $("connection");

  try {
    const data = await api("/api/health");

    status.textContent =
      data.status === "ok" ? "Backend connected" : "Connection issue";

    status.classList.remove("warning");
    status.classList.add("success");
  } catch (error) {
    status.textContent = "Backend disconnected";
    status.classList.add("warning");
    console.error("Health check failed:", error);
  }
}

// Load the sample loans from SQLite.
async function loadLoans() {
  const container = $("loans");

  try {
    const data = await api("/api/loans");
    const loans = data.loans || [];

    container.replaceChildren();
    container.classList.toggle("empty", loans.length === 0);

    if (loans.length === 0) {
      showMessage(container, "No sample loans were found.");
      return;
    }

    for (const loan of loans) {
      const reserved =
        loan.reserved === true ||
        loan.reserved === 1 ||
        loan.reserved === "1";

      const used = Number(loan.renewals_used || 0);
      const limit = Number(
        loan.renewal_limit ?? loan.max_renewals ?? 0
      );

      const status = reserved
        ? "Reserved by another user"
        : used >= limit
          ? "Renewal limit reached"
          : "Eligible based on renewal limits";

      addResult(
        container,
        loan.title || "Untitled book",
        `Loan ID: ${loan.loan_id} · ` +
        `Due date: ${loan.due_date} · ` +
        `Renewals used: ${used}/${limit} · ${status}`
      );
    }
  } catch (error) {
    showMessage(container, `Could not load loans: ${error.message}`);
    console.error("Loan loading failed:", error);
  }
}

// Search the synthetic catalogue.
async function searchCatalog() {
  const query = $("catalogQuery").value.trim();
  const container = $("catalogResults");

  if (!query) {
    showMessage(container, "Enter a book title to search.");
    return;
  }

  showMessage(container, "Searching catalogue...");

  try {
    const data = await api(
      `/api/catalog?q=${encodeURIComponent(query)}`
    );

    container.replaceChildren();
    container.classList.remove("empty");

    const results = data.mock_results || [];

    if (results.length === 0) {
      addResult(
        container,
        "No matching sample editions",
        "Try a different title or keyword."
      );
    }

    for (const book of results) {
      const title =
        book.title || book.name || "Untitled edition";

      const details = [
        book.author ? `Author: ${book.author}` : "",
        book.edition ? `Edition: ${book.edition}` : "",
        book.isbn ? `ISBN: ${book.isbn}` : "",
        book.publisher ? `Publisher: ${book.publisher}` : ""
      ].filter(Boolean).join(" · ");

      addResult(
        container,
        title,
        details || "Sample catalogue edition"
      );
    }

    const live = data.live_opac;

    if (live && live.message) {
      addResult(container, "Live OPAC", live.message);
    } else if (data.message) {
      addResult(container, "Catalogue information", data.message);
    }
  } catch (error) {
    showMessage(container, `Catalogue search failed: ${error.message}`);
    console.error("Catalogue search failed:", error);
  }
}

// Preview a request, then ask for approval when available.
async function previewRequest() {
  const message = $("request").value.trim();
  const accountId = $("account").value;
  const container = $("preview");
  const button = $("previewBtn");

  if (!message) {
    showMessage(container, "Please enter or speak a library request.");
    return;
  }

  button.disabled = true;
  button.textContent = "Preparing...";

  try {
    const data = await api("/api/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        account_id: accountId
      })
    });

    container.replaceChildren();
    container.classList.remove("empty");

    const notice = document.createElement("p");
    notice.textContent = data.message || "Request preview prepared.";
    notice.className = "muted";
    container.appendChild(notice);

    for (const action of data.proposed_actions || []) {
      addResult(
        container,
        action.title || "Proposed action",
        `Action: ${(action.action || "review").toUpperCase()} · ` +
        `Status: ${(action.status || "unknown").replaceAll("_", " ")} · ` +
        `${action.reason || ""}` +
        (action.proposed_due_date
          ? ` · Proposed due date: ${action.proposed_due_date}`
          : "")
      );
    }

    const id = document.createElement("small");
    id.className = "muted";
    id.textContent =
      `Preview ID: ${data.request_id ?? "N/A"} · ` +
      `Approval required: ${Boolean(data.approval_required)} · ` +
      `Executed: ${Boolean(data.executed)}`;

    container.appendChild(id);

    
    if (data.action_id && data.approval_required) {
      const actionType = String(
        (data.proposed_actions || [])
          .map(item => item.action || "")
          .join(" ")
      ).toUpperCase();

      const isReservation =
        actionType.includes("RESERVE") ||
        actionType.includes("HOLD");

      const approveButton = document.createElement("button");
      approveButton.type = "button";
      approveButton.textContent = isReservation
        ? "Approve reservation"
        : "Approve renewal";
      approveButton.style.marginTop = "16px";

      approveButton.addEventListener("click", async () => {
        approveButton.disabled = true;
        approveButton.textContent = "Processing approval...";

        try {
          const result = await api("/api/approve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action_id: data.action_id
            })
          });

          const panel = document.createElement("div");
          panel.className = "result-item";

          const heading = document.createElement("strong");
          heading.textContent =
            result.status === "simulated_success"
              ? (isReservation
                  ? "Simulated reservation verified"
                  : "Simulated renewal verified")
              : (isReservation
                  ? "Reservation result"
                  : "Renewal result");

          panel.appendChild(heading);

          const details = document.createElement("p");
          const results = result.results || [];

          details.textContent = results.length
            ? results.map(item => {
                if (isReservation) {
                  return `${item.title || "Book"}: reservation status ${
                    item.status || item.hold_status ||
                    result.status || "unknown"
                  }, queue position ${
                    item.queue_position ?? "not available"
                  } (${item.verification || "verification not provided"})`;
                }

                return `${item.title || "Book"}: due date ${
                  item.new_due_date || "not available"
                } (${item.verification || result.status || "check result"})`;
              }).join(" | ")
            : result.message || "No verification details returned.";

          panel.appendChild(details);

          const note = document.createElement("small");
          note.className = "muted";
          note.textContent =
            "Synthetic SQLite demo only. No real library action was performed.";

          panel.appendChild(note);
          container.appendChild(panel);

          approveButton.textContent =
            result.status === "simulated_success"
              ? (isReservation
                  ? "Reservation approved (simulated)"
                  : "Renewal approved (simulated)")
              : "Approval processed";

          await loadLoans();
        } catch (error) {
          approveButton.disabled = false;
          approveButton.textContent = isReservation
            ? "Retry reservation approval"
            : "Retry renewal approval";

          const errorMessage = document.createElement("p");
          errorMessage.textContent = error.message;
          errorMessage.className = "muted";
          container.appendChild(errorMessage);
        }
      });

      container.appendChild(approveButton);
    }
 } catch (error) {
    showMessage(container, `Preview failed: ${error.message}`);
    console.error("Preview failed:", error);
  } finally {
    button.disabled = false;
    button.textContent = "Preview request →";
  }
}

// Optional voice input using browser speech recognition.
function setupVoice() {
  const button = $("voiceBtn");
  const status = $("voiceStatus");
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    button.disabled = true;
    status.textContent =
      "Voice input isn't supported in this browser. You can type instead.";
    return;
  }

  const recognition = new SpeechRecognition();
  recognition.lang = "en-IN";
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.onstart = () => {
    button.textContent = "Listening...";
    status.textContent = "Speak your library request.";
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    $("request").value = transcript;
    status.textContent = `Recognised: ${transcript}`;
  };

  recognition.onerror = (event) => {
    status.textContent = `Voice input error: ${event.error}. You can type instead.`;
  };

  recognition.onend = () => {
    button.textContent = "🎙 Speak";
  };

  button.addEventListener("click", () => {
    try {
      recognition.start();
    } catch (error) {
      status.textContent =
        "Voice input is already starting. Please wait a moment.";
    }
  });
}

// Connect the buttons and start the dashboard.
function startApp() {
  $("previewBtn").addEventListener("click", previewRequest);
  $("searchBtn").addEventListener("click", searchCatalog);

  $("catalogQuery").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      searchCatalog();
    }
  });

  setupVoice();
  checkHealth();
  loadLoans();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", startApp);
} else {
  startApp();
}
