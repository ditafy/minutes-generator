const audioInput = document.getElementById("audioInput");
const fileName = document.getElementById("fileName");
const meetingType = document.getElementById("meetingType");
const meetingDate = document.getElementById("meetingDate");
const useOnlineSummary = document.getElementById("useOnlineSummary");
const generateBtn = document.getElementById("generateBtn");

const transcribeStep = document.getElementById("transcribeStep");
const summarizeStep = document.getElementById("summarizeStep");
const statusText = document.getElementById("statusText");

const output = document.getElementById("output");
const copyBtn = document.getElementById("copyBtn");
const downloadBtn = document.getElementById("downloadBtn");

const stageLabels = {
  queued: "等待开始",
  transcribing: "正在识别音频内容...",
  summarizing: "正在整理会议纪要...",
  rendering: "正在生成 Markdown...",
  done: "纪要已生成",
  failed: "生成失败",
};

function setStepState(element, state) {
  element.classList.remove("pending", "active", "done");
  element.classList.add(state);
}

function setProgress(_progress, stage, text) {
  if (stage === "transcribing") {
    setStepState(transcribeStep, "active");
    setStepState(summarizeStep, "pending");
  } else if (stage === "summarizing" || stage === "rendering") {
    setStepState(transcribeStep, "done");
    setStepState(summarizeStep, "active");
  } else if (stage === "done") {
    setStepState(transcribeStep, "done");
    setStepState(summarizeStep, "done");
  } else if (stage === "failed") {
    setStepState(transcribeStep, "done");
    setStepState(summarizeStep, "pending");
  } else {
    setStepState(transcribeStep, "pending");
    setStepState(summarizeStep, "pending");
  }

  statusText.textContent = text || stageLabels[stage] || stageLabels.queued;
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
  generateBtn.disabled = true;

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
    setProgress(0, "failed", `失败：${e.message}`);
  } finally {
    generateBtn.disabled = false;
  }
});

audioInput.addEventListener("change", () => {
  const file = audioInput.files?.[0];
  fileName.textContent = file ? file.name : "选择音频文件";
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

setProgress(0, "queued", "等待音频");
