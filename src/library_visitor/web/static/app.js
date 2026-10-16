"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  meta: null,
  stream: null,
  facing: "environment", // kamera belakang: petugas memotret anggota
  images: [],
  fromDirectory: false,
  directoryStatus: "",
  capturing: false,
};

// ---------- util ----------

async function api(path, options = {}) {
  const init = { credentials: "same-origin", headers: { "X-Requested-With": "penerima-tamu" } };
  if (options.body !== undefined) {
    init.method = "POST";
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch (_) { /* respons kosong */ }
  if (res.status === 401 && path !== "/api/login") showLogin();
  if (!res.ok) {
    const err = new Error(data.error || `Galat ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

let toastTimer = null;
function toast(text, kind = "") {
  const el = $("toast");
  el.textContent = text;
  el.className = "toast " + kind;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 5000);
}

function hint(text, kind = "") {
  const el = $("hint");
  el.textContent = text;
  el.className = "callout " + kind;
}

// ---------- login ----------

function showLogin() {
  stopCamera();
  $("login-view").hidden = false;
  $("register-view").hidden = true;
  $("logout").hidden = true;
  $("pin").focus();
}

async function showRegister() {
  state.meta = await api("/api/meta");
  $("library").textContent = state.meta.library || "Registrasi Anggota";
  $("institution").textContent = state.meta.institution || "";
  const select = $("category");
  select.replaceChildren(...state.meta.categories.map((c) => new Option(c, c)));
  $("lookup").hidden = !state.meta.lookup;
  $("login-view").hidden = true;
  $("register-view").hidden = false;
  $("logout").hidden = false;
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/login", { body: { pin: $("pin").value } });
    $("pin").value = "";
    await showRegister();
  } catch (err) {
    toast(err.message, "error");
  }
});

$("logout").addEventListener("click", async () => {
  await api("/api/logout", { body: {} }).catch(() => {});
  resetForm();
  showLogin();
});

// ---------- data anggota ----------

let searchTimer = null;
let searchSeq = 0;

$("member-no").addEventListener("input", () => {
  state.fromDirectory = false;
  clearTimeout(searchTimer);
  const text = $("member-no").value.trim();
  if (text.length < 2) { hideSuggestions(); return; }
  searchTimer = setTimeout(() => search(text), 300);
});

$("member-no").addEventListener("keydown", (event) => {
  if (event.key === "Enter") { event.preventDefault(); hideSuggestions(); lookup(); }
  if (event.key === "Escape") hideSuggestions();
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".suggest-wrap")) hideSuggestions();
});

async function search(text) {
  const seq = ++searchSeq;
  try {
    const { results } = await api("/api/search?q=" + encodeURIComponent(text));
    if (seq !== searchSeq) return; // hasil basi
    renderSuggestions(results);
  } catch (_) { /* abaikan galat pencarian */ }
}

function renderSuggestions(results) {
  const list = $("suggestions");
  if (!results.length) { hideSuggestions(); return; }
  list.replaceChildren(...results.map((p) => {
    const li = document.createElement("li");
    const no = document.createElement("span");
    no.className = "no";
    no.textContent = `${p.member_no} — ${p.name}`;
    const meta = document.createElement("span");
    meta.className = "meta";
    const tag = p.registered ? (p.has_face ? "terdaftar, wajah ada" : "terdaftar") : (p.status || "direktori");
    meta.textContent = [p.category, p.unit, tag].filter(Boolean).join(" · ");
    li.append(no, meta);
    li.addEventListener("click", () => {
      $("member-no").value = p.member_no;
      hideSuggestions();
      lookup();
    });
    return li;
  }));
  list.hidden = false;
}

function hideSuggestions() { $("suggestions").hidden = true; }

$("lookup").addEventListener("click", () => { hideSuggestions(); lookup(); });

async function lookup() {
  const number = $("member-no").value.trim();
  if (!number) return;
  const status = $("lookup-status");
  status.textContent = "Mencari...";
  $("photo").hidden = true;
  try {
    const p = await api("/api/lookup?no=" + encodeURIComponent(number));
    if (!p.found) {
      status.textContent = "Tidak ditemukan. Isi data secara manual.";
      return;
    }
    $("name").value = p.name;
    $("category").value = p.category;
    $("unit").value = p.unit || "";
    state.fromDirectory = !p.registered;
    state.directoryStatus = p.status || "";
    status.textContent = p.registered
      ? `Sudah terdaftar · wajah ${p.has_face ? "sudah" : "belum"} ada. Simpan untuk memperbarui.`
      : `Dari direktori · ${p.category}${p.status ? " · " + p.status : ""}`;
    if (p.photo) {
      $("photo").src = p.photo;
      $("photo").hidden = false;
    }
  } catch (err) {
    status.textContent = err.message;
  }
}

// ---------- kamera ----------

async function startCamera() {
  stopCamera();
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    hint("Browser tidak mengizinkan kamera. Pastikan laman dibuka lewat https://.", "error");
    return;
  }
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: state.facing, width: { ideal: 1280 }, height: { ideal: 960 } },
    });
  } catch (err) {
    hint("Kamera tidak bisa dibuka: " + (err.message || err.name) + ". Izinkan akses kamera.", "error");
    return;
  }
  const video = $("video");
  video.srcObject = state.stream;
  video.classList.toggle("mirror", state.facing === "user");
  await video.play();
  $("camera-placeholder").hidden = true;
  $("capture").disabled = false;
  $("switch-camera").hidden = false;
  $("start-camera").textContent = "Mulai Ulang";
  hint("Arahkan kamera ke wajah anggota (hanya satu wajah), lalu tekan \"Ambil Wajah\".");
}

function stopCamera() {
  if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
  state.stream = null;
  $("video").srcObject = null;
  $("camera-placeholder").hidden = false;
  $("capture").disabled = true;
}

$("start-camera").addEventListener("click", startCamera);
$("switch-camera").addEventListener("click", () => {
  state.facing = state.facing === "environment" ? "user" : "environment";
  startCamera();
});

function grabFrame() {
  const video = $("video");
  const scale = Math.min(1, 960 / Math.max(video.videoWidth, video.videoHeight));
  const canvas = $("canvas");
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85);
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

$("capture").addEventListener("click", async () => {
  if (state.capturing || !state.stream) return;
  state.capturing = true;
  $("capture").disabled = true;
  state.images = [];
  $("thumbs").replaceChildren();
  const total = state.meta.samples + 2; // cadangan bila ada foto yang ditolak
  for (let i = 1; i <= total; i++) {
    hint(`Mengambil foto ${i} dari ${total}... minta anggota menggerakkan kepala sedikit.`);
    const image = grabFrame();
    state.images.push(image);
    const thumb = document.createElement("img");
    thumb.src = image;
    thumb.alt = `Sampel ${i}`;
    $("thumbs").append(thumb);
    await sleep(450);
  }
  hint(`${total} foto diambil. Centang persetujuan, lalu tekan "Simpan".`, "ok");
  $("capture").disabled = false;
  $("capture").textContent = "Ambil Ulang";
  state.capturing = false;
});

// ---------- simpan ----------

async function save(confirmDuplicate = false) {
  const number = $("member-no").value.trim();
  const name = $("name").value.trim();
  if (!number || !name) { toast("No. anggota dan nama wajib diisi.", "error"); return; }
  if (state.images.length && !$("consent").checked) {
    toast("Centang persetujuan data biometrik dulu.", "error");
    return;
  }
  if (!state.images.length && !confirm("Belum ada foto wajah. Simpan data anggota saja?")) return;
  $("save").disabled = true;
  hint("Memproses foto wajah di server...");
  try {
    const result = await api("/api/register", {
      body: {
        member_no: number,
        name,
        category: $("category").value,
        unit: $("unit").value,
        status: state.directoryStatus,
        from_directory: state.fromDirectory,
        consent: $("consent").checked,
        confirm_duplicate: confirmDuplicate,
        images: state.images,
      },
    });
    const face = result.face_saved ? ` dengan ${result.samples} sampel wajah` : " (tanpa wajah)";
    toast(`Data ${result.name} tersimpan${face}.`, "ok");
    resetForm();
  } catch (err) {
    if (err.status === 409 && confirm(err.message + "\n\nTetap simpan?")) {
      $("save").disabled = false;
      return save(true);
    }
    const problems = (err.data && err.data.problems) || [];
    hint([err.message, ...problems].join("\n"), "error");
    toast(err.message, "error");
  } finally {
    $("save").disabled = false;
  }
}

$("save").addEventListener("click", () => save());
$("reset").addEventListener("click", resetForm);

function resetForm() {
  for (const id of ["member-no", "name", "unit"]) $(id).value = "";
  if (state.meta) $("category").value = state.meta.categories[0];
  $("consent").checked = false;
  $("photo").hidden = true;
  $("photo").removeAttribute("src");
  $("lookup-status").textContent = "";
  $("thumbs").replaceChildren();
  $("capture").textContent = "Ambil Wajah";
  state.images = [];
  state.fromDirectory = false;
  state.directoryStatus = "";
  hideSuggestions();
  hint("Arahkan kamera ke wajah anggota (hanya satu wajah), lalu tekan \"Ambil Wajah\".");
}

// ---------- mulai ----------

(async () => {
  try {
    const { authenticated } = await api("/api/session");
    if (authenticated) await showRegister();
    else showLogin();
  } catch (_) {
    showLogin();
  }
})();
