const audioInput = document.getElementById("audioInput");
const meetingType = document.getElementById("meetingType");
const meetingDate = document.getElementById("meetingDate");
const useOnlineSummary = document.getElementById("useOnlineSummary");
const meetingHint = document.getElementById("meetingHint");
const generateBtn = document.getElementById("generateBtn");

const stageEl = document.getElementById("stage");
const progressEl = document.getElementById("progress");
const progressBar = document.getElementById("progressBar");
const statusText = document.getElementById("statusText");

const output = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");
const downloadBtn = document.getElementById("downloadBtn");

const meetingHints = {
  management_weekly: "管理层周例会将重点输出部门进展、协同问题、本周决定和 Todo。",
  recruitment_prep: "招聘会筹备会议将重点输出本周进展、补充信息、下周重点、关键决策和 Todo。",
};

function setProgress(progress, stage, text) {
  progressEl.textContent = progress;
  stageEl.textContent = stage;
  progressBar.style.width = `${progress}%`;
  statusText.textContent = text || "";
}

function updateMeetingHint() {
  meetingHint.textContent = meetingHints[meetingType.value] || "";
}

async function pollJob(jobId) {
  while (true) {
    const res = await fetch(`/api/v1/jobs/${jobId}`);
    if (!res.ok) throw new Error(`job status failed: ${res.status}`);
    const data = await res.json();
    const warningText = data.warning ? ` ${data.warning}` : "";
    setProgress(
      data.progress ?? 0,
      data.stage ?? data.status ?? "unknown",
      data.error ? `错误：${data.error}` : `${data.summaryMode || ""}${warningText}`.trim()
    );

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
  form.append("meeting_type", meetingType.value);
  form.append("meeting_date", meetingDate.value || "");
  form.append("use_online_summary", useOnlineSummary.checked ? "true" : "false");

  try {
    const res = await fetch("/api/v1/jobs", { method: "POST", body: form });
    if (!res.ok) {
      const errText = await res.text();
      throw new Error(`create job failed: ${res.status} ${errText}`);
    }
    const data = await res.json();
    const jobId = data.jobId;

    await pollJob(jobId);
    const result = await fetchResult(jobId);
    output.value = result.markdown || "";

    const doneText = result.warning
      ? `生成完成。${result.warning}`
      : `生成完成（${result.summaryMode || "offline"}）`;
    setProgress(100, "done", doneText);
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

meetingType.addEventListener("change", updateMeetingHint);
updateMeetingHint();
