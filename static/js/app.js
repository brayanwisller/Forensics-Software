/**
 * Indício - frontend
 */
(function () {
  "use strict";
  const state = {
    view: "home", caseReady: false, caseName: null,
    chats: [], currentChatId: null, currentChat: null,
    messages: [], offset: 0, limit: 80, msgQ: "", focusId: null,
    selectedContact: null, galleryType: "all", galleryOffset: 0,
    hourlyFocusIds: [],
  };
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const app = $("#app");

  function initials(n) {
    if (!n) return "?";
    const p = n.trim().split(/\s+/);
    return (p.length >= 2 ? p[0][0] + p[1][0] : n.slice(0, 2)).toUpperCase();
  }
  function esc(s) {
    return (s || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }
  function linkify(t) {
    return esc(t).replace(/(https?:\/\/[^\s<]+)/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
  }
  function hl(t, q) {
    if (!q) return linkify(t);
    const e = esc(t), qq = esc(q);
    return e.replace(new RegExp(`(${qq.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")})`,"gi"), '<span class="highlight">$1</span>');
  }
  function fmtSize(b) {
    if (!b) return "";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    return (b / 1048576).toFixed(1) + " MB";
  }
  function icon(id, cls) {
    return `<svg class="icon ${cls || "icon-sm"}"><use href="#${id}"/></svg>`;
  }
  async function api(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error("HTTP " + res.status);
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("json")) return res.json();
    return res;
  }

  /* Interactive bar chart */
  function renderIBar(container, labels, counts, opts) {
    opts = opts || {};
    const max = Math.max(...counts, 1);
    const showEvery = labels.length > 24 ? Math.ceil(labels.length / 12) : (labels.length > 12 ? 2 : 1);
    container.innerHTML = labels.map((lab, i) => {
      const c = counts[i] || 0;
      const pct = Math.max(c ? 3 : 0, (c / max) * 100);
      const clickable = opts.onClick && c > 0 ? "clickable" : "";
      const label = (i % showEvery === 0) ? `<span class="ibar-label">${esc(lab)}</span>` : "";
      return `<div class="ibar-col ${clickable}" data-i="${i}" title="${esc(lab)}: ${c}">
        <span class="ibar-tip">${esc(lab)} · <strong>${c}</strong></span>
        <div class="ibar-bar" style="height:${pct}%"></div>
        ${label}
      </div>`;
    }).join("");
    if (opts.onClick) {
      container.querySelectorAll(".ibar-col.clickable").forEach((col) => {
        col.addEventListener("click", () => opts.onClick(+col.dataset.i, labels[+col.dataset.i], counts[+col.dataset.i]));
      });
    }
  }

  /* Navigation */
  function go(view) {
    state.view = view;
    app.dataset.view = view;
    $$(".view").forEach((v) => v.classList.add("hidden"));
    const el = $("#view-" + view);
    if (el) el.classList.remove("hidden");
    app.classList.remove("show-chat");
    if (view === "chat") { loadChats(); $("#chat-case-name").textContent = state.caseName || ""; }
    if (view === "analysis") { $("#an-case-name").textContent = state.caseName || ""; loadAnalysisPanel("dashboard"); }
    if (view === "home") refreshCaseStatus();
  }
  $$("[data-go]").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.go;
    if ((v === "chat" || v === "analysis") && !state.caseReady) return;
    go(v);
  }));

  async function refreshCaseStatus() {
    try {
      const s = await api("/api/case/status");
      state.caseReady = !!s.ready;
      state.caseName = s.name;
      const box = $("#home-case");
      if (s.ready) {
        box.textContent = "Caso ativo: " + (s.name || "sem nome");
        box.classList.add("ready");
        $("#card-chat").disabled = false;
        $("#card-analysis").disabled = false;
      } else {
        box.textContent = "Nenhum caso carregado - use Carregar caso";
        box.classList.remove("ready");
        $("#card-chat").disabled = true;
        $("#card-analysis").disabled = true;
      }
    } catch (e) {
      $("#home-case").textContent = "Erro ao verificar caso";
    }
  }

  /* Upload */
  const fileInput = $("#file-input");
  const dropzone = $("#dropzone");
  $("#btn-pick")?.addEventListener("click", () => fileInput.click());
  dropzone?.addEventListener("click", (e) => { if (e.target === dropzone || e.target.closest(".upload-title")) fileInput.click(); });
  dropzone?.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("drag"); });
  dropzone?.addEventListener("dragleave", () => dropzone.classList.remove("drag"));
  dropzone?.addEventListener("drop", (e) => {
    e.preventDefault(); dropzone.classList.remove("drag");
    if (e.dataTransfer.files[0]) doUpload(e.dataTransfer.files[0]);
  });
  fileInput?.addEventListener("change", () => { if (fileInput.files[0]) doUpload(fileInput.files[0]); });

  async function doUpload(file) {
    const st = $("#upload-status");
    st.className = "upload-status";
    st.textContent = "Enviando e extraindo " + file.name + "…";
    const fd = new FormData();
    fd.append("file", file, file.name);
    try {
      const res = await fetch("/api/case/upload", { method: "POST", body: fd });
      const data = await res.json();
      if (!res.ok || data.error) {
        st.className = "upload-status err";
        st.textContent = data.error || "Falha no upload";
        return;
      }
      st.className = "upload-status ok";
      st.textContent = data.message || "Caso carregado.";
      state.caseReady = true;
      state.caseName = data.name;
      setTimeout(() => go("home"), 700);
    } catch (e) {
      st.className = "upload-status err";
      st.textContent = e.message;
    }
  }
  $("#btn-default-case")?.addEventListener("click", async () => {
    const st = $("#upload-status");
    st.textContent = "Ativando caso padrão…";
    try {
      const data = await api("/api/case/activate-default", { method: "POST" });
      if (data.ok) {
        st.className = "upload-status ok";
        st.textContent = "Caso padrão ativado.";
        state.caseReady = true;
        state.caseName = data.status?.name || "caso_padrao";
        setTimeout(() => go("home"), 500);
      } else {
        st.className = "upload-status err";
        st.textContent = "Caso padrão não encontrado.";
      }
    } catch (e) {
      st.className = "upload-status err";
      st.textContent = e.message;
    }
  });

  /* Chats */
  function previewIcon(type) {
    if (type === "image") return icon("i-image");
    if (type === "audio") return icon("i-mic");
    if (type === "video") return icon("i-image");
    return "";
  }
  async function loadChats(q) {
    try {
      const data = await api("/api/chats?q=" + encodeURIComponent(q || ""));
      state.chats = data.chats || [];
      renderChatList();
    } catch (e) {
      $("#chat-list").innerHTML = `<div class="empty-state"><p>${esc(e.message)}</p></div>`;
    }
  }
  function renderChatList() {
    const list = $("#chat-list");
    if (!state.chats.length) {
      list.innerHTML = '<div style="padding:28px;color:var(--text-3);text-align:center;font-size:13px">Nenhuma conversa</div>';
      return;
    }
    list.innerHTML = state.chats.map((c) => {
      const preview = c.last_text
        ? `${previewIcon(c.last_type)}<span>${esc(c.last_text)}</span>`
        : '<span style="color:var(--text-3)">Sem mensagens</span>';
      return `<div class="chat-item ${c.id === state.currentChatId ? "active" : ""}" data-id="${c.id}">
        <div class="chat-avatar ${c.is_group ? "group" : ""}">${initials(c.name)}</div>
        <div class="chat-meta">
          <div class="chat-top">
            <span class="chat-name">${esc(c.name)}${c.is_group ? '<span class="tag">grupo</span>' : ""}</span>
            <span class="chat-date">${esc(c.last_date_short || c.last_date)}</span>
          </div>
          <div class="chat-preview">${preview}</div>
        </div>
      </div>`;
    }).join("");
    list.querySelectorAll(".chat-item").forEach((el) => el.addEventListener("click", () => openChat(+el.dataset.id)));
  }

  async function openChat(chatId, focusMsgId) {
    state.currentChatId = chatId;
    state.offset = 0;
    state.messages = [];
    state.focusId = focusMsgId || null;
    state.msgQ = "";
    if ($("#msg-search")) $("#msg-search").value = "";
    renderChatList();
    app.classList.add("show-chat");
    $("#empty-state").classList.add("hidden");
    $("#conversation").classList.remove("hidden");
    $("#messages").innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-3)">Carregando…</div>';
    try {
      let url = `/api/messages/${chatId}?limit=${focusMsgId ? 400 : state.limit}&offset=0`;
      if (focusMsgId) url += "&focus=" + focusMsgId;
      const [info, msgs] = await Promise.all([api("/api/chat/" + chatId), api(url)]);
      state.currentChat = info;
      state.messages = msgs.messages;
      state.offset = msgs.messages.length;
      $("#conv-name").textContent = info.name;
      $("#conv-avatar").textContent = initials(info.name);
      $("#conv-avatar").className = "avatar" + (info.is_group ? " group" : "");
      $("#conv-subtitle").textContent = info.is_group
        ? `${info.members.length} participantes · ${info.message_count} msgs`
        : `${info.message_count} mensagens`;
      renderMessages(!focusMsgId);
      $("#load-more-bar").classList.toggle("hidden", !msgs.has_more);
      $("#info-panel").classList.add("hidden");
      if (focusMsgId) {
        requestAnimationFrame(() => {
          const el = document.querySelector(`[data-msgid="${focusMsgId}"]`);
          if (el) {
            el.classList.add("highlight-msg");
            el.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        });
      }
    } catch (e) {
      $("#messages").innerHTML = `<div style="padding:24px;color:var(--danger)">${esc(e.message)}</div>`;
    }
  }

  function renderMessages(scrollBottom) {
    const box = $("#messages");
    if (!state.messages.length) {
      box.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-3)">Sem mensagens</div>';
      return;
    }
    let html = "", last = null;
    for (const m of state.messages) {
      if (m.date_separator && m.date_separator !== last) {
        last = m.date_separator;
        html += `<div class="date-separator"><span>${esc(m.date_separator)}</span></div>`;
      }
      if (m.type === "system" || m.type_raw === 10 || m.type_raw === 6) {
        html += `<div class="msg-row system-msg" data-msgid="${m.id}"><div class="bubble">${esc(m.text || "Sistema")} <span class="bubble-time">${esc(m.time)}</span></div></div>`;
        continue;
      }
      const me = m.is_from_me;
      let body = "";
      const sender = (!me && m.sender && state.currentChat?.is_group)
        ? `<div class="sender-name">${esc(m.sender)}</div>` : "";
      if (m.type === "image" || m.type === "video") {
        if (m.media_url) {
          const dl = m.download_url || m.media_url.replace("/media/", "/download/");
          body += `<div class="bubble-media">
            <img src="${m.media_url}" loading="lazy" data-full="${m.media_url}" data-dl="${dl}" alt="Prévia"
              onerror="this.style.display='none';this.parentNode.querySelector('.media-fallback')?.classList.remove('hidden')"/>
            <div class="media-placeholder media-fallback hidden">${icon("i-image")} Arquivo local ausente</div>
            <div class="media-actions"><a href="${dl}" download onclick="event.stopPropagation()">${icon("i-download")} Baixar</a></div>
          </div>`;
        } else {
          body += `<div class="media-placeholder">${icon("i-image")} ${m.type === "video" ? "Vídeo" : "Imagem"} não disponível no caso${m.file_size ? " · " + fmtSize(m.file_size) : ""}</div>`;
        }
        if (m.text) body += `<div class="bubble-text">${hl(m.text, state.msgQ)}</div>`;
      } else if (m.type === "audio") {
        if (m.media_url) {
          const dl = m.download_url || m.media_url.replace("/media/", "/download/");
          body += `<div class="bubble-audio">
            <div style="display:flex;align-items:center;gap:6px;color:var(--text-2);font-size:12px;margin-bottom:4px">${icon("i-mic")} Áudio</div>
            <audio controls preload="metadata" src="${m.media_url}"></audio>
            <div style="margin-top:6px"><a class="btn-chip" href="${dl}" download>${icon("i-download")} Baixar</a></div>
          </div>`;
        } else {
          body += `<div class="media-placeholder">${icon("i-mic")} Áudio não disponível no caso</div>`;
        }
      } else if (m.text) {
        body += `<div class="bubble-text">${hl(m.text, state.msgQ)}</div>`;
      } else if (m.media_url) {
        const isA = /audio/i.test(m.media_url);
        if (isA) body += `<audio controls preload="metadata" src="${m.media_url}"></audio>`;
        else body += `<div class="bubble-media"><img src="${m.media_url}" data-full="${m.media_url}" data-dl="${m.media_url.replace("/media/","/download/")}" alt=""/></div>`;
      } else {
        body += `<div class="media-placeholder">[${esc(m.type)}]</div>`;
      }
      body += `<div class="bubble-meta"><span class="bubble-time">${esc(m.time)}</span></div>`;
      html += `<div class="msg-row ${me ? "from-me" : "from-them"}" data-msgid="${m.id}"><div class="bubble">${sender}${body}</div></div>`;
    }
    box.innerHTML = html;
    box.querySelectorAll(".bubble-media img").forEach((img) => {
      img.addEventListener("click", () => {
        if (img.style.display === "none") return;
        openLightbox(img.dataset.full || img.src, img.dataset.dl);
      });
    });
    if (scrollBottom && !state.focusId) box.scrollTop = box.scrollHeight;
  }

  async function loadMore() {
    const btn = $("#btn-load-more");
    btn.textContent = "…"; btn.disabled = true;
    try {
      const data = await api(`/api/messages/${state.currentChatId}?limit=${state.limit}&offset=${state.offset}`);
      const oldH = $("#messages").scrollHeight;
      state.messages = [...data.messages, ...state.messages];
      state.offset += data.messages.length;
      renderMessages(false);
      $("#messages").scrollTop = $("#messages").scrollHeight - oldH;
      $("#load-more-bar").classList.toggle("hidden", !data.has_more);
    } finally {
      btn.textContent = "Mensagens anteriores"; btn.disabled = false;
    }
  }

  /* Analysis */
  function loadAnalysisPanel(name) {
    $$(".anav").forEach((b) => b.classList.toggle("active", b.dataset.panel === name));
    $$(".apanel").forEach((p) => p.classList.add("hidden"));
    const p = $("#apanel-" + name);
    if (p) p.classList.remove("hidden");
    $("#contact-picker").classList.toggle("hidden", name !== "contacts");
    if (name === "dashboard") loadDashboard();
    if (name === "contacts") loadAllContacts();
    if (name === "gallery") { state.galleryOffset = 0; loadGallery(true); }
  }
  $$(".anav").forEach((b) => b.addEventListener("click", () => loadAnalysisPanel(b.dataset.panel)));

  async function loadDashboard() {
    const s = await api("/api/stats");
    $("#dash-stats").innerHTML = [
      ["Conversas", s.chats],
      ["Mensagens", s.messages?.toLocaleString("pt-BR")],
      ["Grupos", s.groups],
      ["Itens de mídia", s.media_items?.toLocaleString("pt-BR")],
      ["Arquivos no caso", s.local_media_files],
      ["Período", `${s.date_from || "-"} → ${s.date_to || "-"}`],
    ].map(([l, v]) => `<div class="stat-card"><div class="stat-value" style="${String(v).length > 14 ? "font-size:13px" : ""}">${esc(String(v ?? "-"))}</div><div class="stat-label">${l}</div></div>`).join("");
    const h = await api("/api/hourly");
    renderIBar($("#chart-hourly-global"), h.labels, h.counts);
  }

  async function loadAllContacts() {
    $("#contacts-overview").classList.remove("hidden");
    $("#contact-detail").classList.add("hidden");
    state.selectedContact = null;
    const data = await api("/api/contacts");
    const max = data.contacts[0]?.message_count || 1;
    const render = (list) => {
      $("#all-contacts").innerHTML = list.map((c) => `
        <div class="ac-row" data-id="${c.id}">
          <div class="chat-avatar ${c.is_group ? "group" : ""}" style="width:36px;height:36px;font-size:12px">${initials(c.name)}</div>
          <div style="width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500">${esc(c.name)}</div>
          <div class="ac-bar-wrap"><div class="ac-bar" style="width:${(c.message_count / max) * 100}%"></div></div>
          <div class="ac-count">${c.message_count}</div>
        </div>`).join("");
      $("#all-contacts").querySelectorAll(".ac-row").forEach((el) => {
        el.addEventListener("click", () => selectContact(+el.dataset.id, list.find((x) => x.id === +el.dataset.id)));
      });
    };
    render(data.contacts);
    $("#contact-list").innerHTML = data.contacts.map((c) => `
      <div class="contact-item" data-id="${c.id}">
        <div class="chat-avatar ${c.is_group ? "group" : ""}" style="width:32px;height:32px;font-size:11px">${initials(c.name)}</div>
        <div class="chat-meta"><div class="chat-name">${esc(c.name)}</div>
        <div class="chat-preview">${c.message_count} msgs</div></div>
      </div>`).join("");
    $("#contact-list").querySelectorAll(".contact-item").forEach((el) => {
      el.addEventListener("click", () => selectContact(+el.dataset.id, data.contacts.find((x) => x.id === +el.dataset.id)));
    });
    state._allContacts = data.contacts;
    state._renderContacts = render;
  }
  $("#contact-filter")?.addEventListener("input", () => {
    const q = $("#contact-filter").value.trim().toLowerCase();
    const list = (state._allContacts || []).filter((c) => !q || (c.name || "").toLowerCase().includes(q));
    if (state._renderContacts) state._renderContacts(list);
  });

  async function selectContact(id, info) {
    state.selectedContact = info || { id, name: "#" + id };
    $("#contacts-overview").classList.add("hidden");
    $("#contact-detail").classList.remove("hidden");
    $("#cd-name").textContent = state.selectedContact.name;
    $("#cd-meta").textContent = (state.selectedContact.message_count || "") + " mensagens · id " + id;
    showContactTab("hourly");
  }
  $("#btn-back-contacts")?.addEventListener("click", () => {
    $("#contact-detail").classList.add("hidden");
    $("#contacts-overview").classList.remove("hidden");
  });
  $$(".cd-tab").forEach((t) => t.addEventListener("click", () => showContactTab(t.dataset.tab)));

  function openChatAtHour(hourIndex) {
    const id = state.selectedContact?.id;
    if (!id) return;
    const focusId = state.hourlyFocusIds[hourIndex];
    go("chat");
    openChat(id, focusId || null);
  }

  async function showContactTab(tab) {
    $$(".cd-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === tab));
    $$(".cd-pane").forEach((p) => p.classList.add("hidden"));
    const id = state.selectedContact?.id;
    if (!id) return;
    if (tab === "openchat") { go("chat"); openChat(id); return; }
    if (tab === "hourly") {
      $("#cd-hourly").classList.remove("hidden");
      const h = await api("/api/hourly?chat_id=" + id);
      state.hourlyFocusIds = h.focus_ids || [];
      renderIBar($("#chart-hourly-contact"), h.labels, h.counts, {
        onClick: (i) => openChatAtHour(i),
      });
      const rows = h.labels.map((l, i) => h.counts[i]
        ? `<tr class="click-row" data-i="${i}"><td>${esc(l)}</td><td>${h.counts[i]}</td></tr>` : "").join("");
      $("#hourly-table").innerHTML = `<table><thead><tr><th>Hora</th><th>Mensagens</th></tr></thead><tbody>${rows}</tbody></table>`;
      $("#hourly-table").querySelectorAll("tr.click-row").forEach((tr) => {
        tr.addEventListener("click", () => openChatAtHour(+tr.dataset.i));
      });
    }
    if (tab === "daily") {
      $("#cd-daily").classList.remove("hidden");
      const t = await api("/api/timeline?chat_id=" + id);
      let labels = t.labels, counts = t.counts;
      if (labels.length > 120) {
        const step = Math.ceil(labels.length / 120);
        labels = labels.filter((_, i) => i % step === 0);
        counts = counts.filter((_, i) => i % step === 0);
      }
      renderIBar($("#chart-daily-contact"), labels, counts);
    }
    if (tab === "words") {
      $("#cd-words").classList.remove("hidden");
      const w = await api("/api/words?chat_id=" + id + "&limit=50");
      const max = w.words[0]?.count || 1;
      $("#word-cloud").innerHTML = w.words.map((x) =>
        `<span style="font-size:${12 + (x.count / max) * 26}px" title="${x.count} ocorrências">${esc(x.text)}</span>`
      ).join(" ") || "<span style='color:var(--text-3)'>Sem texto suficiente</span>";
    }
  }

  /* Gallery */
  async function loadGallery(reset) {
    if (reset) { state.galleryOffset = 0; $("#gallery-grid").innerHTML = ""; }
    const q = ($("#gallery-search")?.value || "").trim();
    const data = await api(`/api/media?type=${state.galleryType}&limit=60&offset=${state.galleryOffset}&q=${encodeURIComponent(q)}`);
    if (!data.items.length && reset) {
      $("#gallery-grid").innerHTML = '<p style="color:var(--text-3);padding:20px 0">Nenhum arquivo encontrado' + (q ? ' para este chat' : '') + '. O caso pode ter só parte da mídia.</p>';
      $("#gallery-more").classList.add("hidden");
      return;
    }
    const html = data.items.map((item) => {
      const locateBtn = item.chat_id
        ? `<button class="locate" data-chat="${item.chat_id}" data-msg="${item.message_id || ""}">${icon("i-locate")} Localizar</button>`
        : "";
      if (item.category === "image") {
        return `<div class="gallery-item">
          <img src="${item.url}" loading="lazy" data-full="${item.url}" data-dl="${item.download_url}" alt=""/>
          <div class="gmeta"><strong title="${esc(item.name)}">${esc(item.name)}</strong><span class="gsub">${esc(item.chat_name || "Chat desconhecido")}${item.msg_date ? " · " + esc(item.msg_date) : ""}${item.size_human ? " · " + esc(item.size_human) : ""}</span></div>
          <div class="gactions">
            <a href="${item.download_url}" download>${icon("i-download")} Baixar</a>
            <button data-view="${item.url}" data-dl="${item.download_url}">Ver</button>
            ${locateBtn}
          </div>
        </div>`;
      }
      return `<div class="gallery-item">
        <div class="gallery-audio">${icon("i-mic")} Áudio<audio controls preload="none" src="${item.url}"></audio></div>
        <div class="gmeta"><strong title="${esc(item.name)}">${esc(item.name)}</strong><span class="gsub">${esc(item.chat_name || "Chat desconhecido")}${item.size_human ? " · " + esc(item.size_human) : ""}</span></div>
        <div class="gactions"><a href="${item.download_url}" download>Baixar</a>${locateBtn}</div>
      </div>`;
    }).join("");
    if (reset) $("#gallery-grid").innerHTML = html;
    else $("#gallery-grid").insertAdjacentHTML("beforeend", html);
    state.galleryOffset += data.items.length;
    $("#gallery-more").classList.toggle("hidden", !data.has_more);
    const grid = $("#gallery-grid");
    grid.querySelectorAll("img[data-full]").forEach((img) => {
      img.addEventListener("click", () => openLightbox(img.dataset.full, img.dataset.dl));
    });
    grid.querySelectorAll("button[data-view]").forEach((b) => {
      b.addEventListener("click", () => openLightbox(b.dataset.view, b.dataset.dl));
    });
    grid.querySelectorAll("button.locate").forEach((b) => {
      b.addEventListener("click", () => {
        go("chat");
        openChat(+b.dataset.chat, b.dataset.msg ? +b.dataset.msg : null);
      });
    });
  }
  $$(".gfilter").forEach((b) => b.addEventListener("click", () => {
    $$(".gfilter").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.galleryType = b.dataset.type;
    loadGallery(true);
  }));
  let gt;
  $("#gallery-search")?.addEventListener("input", () => { clearTimeout(gt); gt = setTimeout(() => loadGallery(true), 300); });
  $("#btn-gallery-more")?.addEventListener("click", () => loadGallery(false));

  /* Global search */
  let gst;
  $("#global-search")?.addEventListener("input", () => {
    clearTimeout(gst);
    gst = setTimeout(async () => {
      const q = $("#global-search").value.trim();
      if (q.length < 2) { $("#global-results").innerHTML = ""; return; }
      const data = await api("/api/search?q=" + encodeURIComponent(q));
      $("#global-results").innerHTML = data.results.map((r) => `
        <div class="result-item" data-chat="${r.chat_id}" data-msg="${r.id}">
          <div class="result-chat">${esc(r.chat_name)}</div>
          <div class="result-text">${hl(r.text, q)}</div>
          <div class="result-date">${esc(r.date)}</div>
        </div>`).join("") || '<p style="color:var(--text-3)">Nenhum resultado</p>';
      $("#global-results").querySelectorAll(".result-item").forEach((el) => {
        el.addEventListener("click", () => { go("chat"); openChat(+el.dataset.chat, +el.dataset.msg); });
      });
    }, 350);
  });

  function openLightbox(src, dl) {
    $("#lightbox-img").src = src;
    $("#lightbox-dl").href = dl || src.replace("/media/", "/download/");
    $("#lightbox").classList.remove("hidden");
  }
  function closeLightbox() {
    $("#lightbox").classList.add("hidden");
    $("#lightbox-img").src = "";
  }
  $("#lightbox-close")?.addEventListener("click", closeLightbox);
  $("#lightbox")?.addEventListener("click", (e) => { if (e.target.id === "lightbox") closeLightbox(); });

  $("#chat-search")?.addEventListener("input", () => {
    clearTimeout($("#chat-search")._t);
    $("#chat-search")._t = setTimeout(() => loadChats($("#chat-search").value.trim()), 250);
  });
  $("#msg-search")?.addEventListener("input", () => {
    clearTimeout($("#msg-search")._t);
    $("#msg-search")._t = setTimeout(async () => {
      state.msgQ = $("#msg-search").value.trim();
      if (!state.currentChatId) return;
      const url = state.msgQ
        ? `/api/messages/${state.currentChatId}?limit=200&offset=0&q=${encodeURIComponent(state.msgQ)}`
        : `/api/messages/${state.currentChatId}?limit=${state.limit}&offset=0`;
      const data = await api(url);
      state.messages = data.messages;
      state.offset = data.messages.length;
      renderMessages(true);
      $("#load-more-bar").classList.toggle("hidden", !data.has_more || !!state.msgQ);
    }, 350);
  });
  $("#btn-load-more")?.addEventListener("click", loadMore);
  $("#btn-export-txt")?.addEventListener("click", () => state.currentChatId && window.open("/api/export/" + state.currentChatId + "/txt"));
  $("#btn-export-html")?.addEventListener("click", () => state.currentChatId && window.open("/api/export/" + state.currentChatId + "/html"));
  $("#btn-info")?.addEventListener("click", () => {
    if (!state.currentChat) return;
    const c = state.currentChat;
    let html = `<div class="info-avatar-large">${initials(c.name)}</div>
      <div class="info-name">${esc(c.name)}</div><div class="info-jid">${esc(c.jid || "")}</div>
      <p style="color:var(--text-2);font-size:13px">${c.is_group ? "Grupo" : "Individual"} · ${c.message_count} mensagens</p>`;
    if (c.members?.length) {
      html += `<p style="margin-top:16px;color:var(--text-3);font-size:11px;text-transform:uppercase;letter-spacing:.04em">Participantes</p>`;
      html += c.members.map((m) => `<div class="member-item"><div class="chat-avatar" style="width:32px;height:32px;font-size:11px">${initials(m.name)}</div>
        <div>${esc(m.name)}<div style="font-size:11px;color:var(--text-3)">${m.is_admin ? "Admin" : "Membro"}</div></div></div>`).join("");
    }
    $("#info-content").innerHTML = html;
    $("#info-panel").classList.toggle("hidden");
  });
  $("#btn-close-info")?.addEventListener("click", () => $("#info-panel").classList.add("hidden"));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLightbox(); });

  refreshCaseStatus();
})();
