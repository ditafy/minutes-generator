const audioInput = document.getElementById("audioInput");
const meetingTitle = document.getElementById("meetingTitle");
const meetingDate = document.getElementById("meetingDate");
const clubName = document.getElementById("clubName");
const generateBtn = document.getElementById("generateBtn");

const stageEl = document.getElementById("stage");
const progressEl = document.getElementById("progress");
const progressBar = document.getElementById("progressBar");
const statusText = document.getElementById("statusText");

const output = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");
const downloadBtn = document.getElementById("downloadBtn");

function setProgress(progress, stage, text) {
  progressEl.textContent = progress;
  stageEl.textContent = stage;
  progressBar.style.width = `${progress}%`;
  statusText.textContent = text || "";
}

async function pollJob(jobId) {
  while (true) {
    const res = await fetch(`/api/v1/jobs/${jobId}`);
    if (!res.ok) throw new Error(`job status failed: ${res.status}`);
    const data = await res.json();

    setProgress(data.progress ?? 0, data.stage ?? data.status ?? "unknown", data.error ? `错误：${data.error}` : "");

    if (data.status === "success") return data;
    if (data.status === "failed") throw new Error(data.error || "job failed");

    await new Promise((r) => setTimeout(r, 2000));
  }
}

async function fetchResult(jobId) {
  const res = await fetch(`/api/v1/jobs/${jobId}/result`);
  if (!res.ok) throw new Error(`result fetch failed: ${res.status}`);
  return res.json();
}

generateBtn.addEventListener("click", async () => {
  const file = audioInput.files?.[0];
  if (!file) {
    alert("请先选择音频文件");
    return;
  }

  output.value = "";
  setProgress(0, "queued", "已提交，等待开始...");

  const form = new FormData();
  form.append("audio", file);
  form.append("meeting_title", meetingTitle.value || "");
  form.append("meeting_date", meetingDate.value || "");
  form.append("club_name", clubName.value || "");

  const res = await fetch("/api/v1/jobs", { method: "POST", body: form });
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`create job failed: ${res.status} ${errText}`);
  }
  const data = await res.json();
  const jobId = data.jobId;

  try {
    await pollJob(jobId);
    const result = await fetchResult(jobId);
    output.value = result.markdown || "";
    setProgress(100, "done", "生成完成");
  } catch (e) {
    setProgress(progressEl.textContent, stageEl.textContent, `失败：${e.message}`);
  }
});

copyBtn.addEventListener("click", async () => {
  if (!output.value) return;
  await navigator.clipboard.writeText(output.value);
  alert("已复制到剪贴板");
});

downloadBtn.addEventListener("click", () => {
  if (!output.value) return;
  const blob = new Blob([output.value], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "会议纪要.md";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
});

