import fs from "node:fs/promises";
import path from "node:path";

const appUrl = process.argv[2] || "http://127.0.0.1:8502";
const outputDir = path.resolve(process.argv[3] || "tmp/qa-streamlit");
const cdpBase = process.argv[4] || "http://127.0.0.1:9223";

await fs.mkdir(outputDir, { recursive: true });

const targets = await (await fetch(`${cdpBase}/json/list`)).json();
const target = targets.find((item) => item.type === "page");
if (!target?.webSocketDebuggerUrl) {
  throw new Error("No Chrome page target is available.");
}

const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

let nextId = 1;
const pending = new Map();
const consoleErrors = [];
const pageErrors = [];
const failedRequests = [];

socket.addEventListener("message", (event) => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    if (message.error) task.reject(new Error(message.error.message));
    else task.resolve(message.result || {});
    return;
  }
  if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") {
    consoleErrors.push(
      (message.params.args || []).map((item) => item.value || item.description || "").join(" ")
    );
  }
  if (message.method === "Runtime.exceptionThrown") {
    pageErrors.push(message.params.exceptionDetails?.text || "Runtime exception");
  }
  if (message.method === "Log.entryAdded" && message.params.entry?.level === "error") {
    consoleErrors.push(message.params.entry.text);
  }
  if (message.method === "Network.loadingFailed" && !message.params.canceled) {
    failedRequests.push(message.params.errorText || "Network request failed");
  }
});

function send(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

async function evaluate(expression, returnByValue = true) {
  const result = await send("Runtime.evaluate", {
    expression,
    returnByValue,
    awaitPromise: true,
    userGesture: true,
  });
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || "Evaluation failed");
  }
  return result.result?.value;
}

async function waitFor(expression, label, timeoutMs = 45000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await evaluate(expression)) return;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  throw new Error(`Timed out waiting for ${label}`);
}

async function clickButton(label) {
  const clicked = await evaluate(`(() => {
    const button = [...document.querySelectorAll("button")].find(
      (item) => item.innerText.trim() === ${JSON.stringify(label)}
    );
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) {
    const labels = await evaluate(
      `[...document.querySelectorAll("button")].map((item) => ({label: item.innerText.trim(), disabled: item.disabled}))`
    );
    throw new Error(`Button is missing or disabled: ${label}; buttons=${JSON.stringify(labels)}`);
  }
}

async function capture(name, fullPage = false) {
  if (fullPage) {
    const fullHeight = await evaluate(`Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
      document.querySelector('[data-testid="stAppViewContainer"]')?.scrollHeight || 0,
      document.querySelector('.stApp')?.scrollHeight || 0
    )`);
    await send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: Math.min(10000, Math.max(1318, fullHeight)),
      deviceScaleFactor: 1,
      mobile: false,
    });
    await new Promise((resolve) => setTimeout(resolve, 500));
    const result = await send("Page.captureScreenshot", {
      format: "png",
      fromSurface: true,
      captureBeyondViewport: true,
    });
    const filePath = path.join(outputDir, name);
    await fs.writeFile(filePath, Buffer.from(result.data, "base64"));
    await send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 1318,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await new Promise((resolve) => setTimeout(resolve, 500));
    return filePath;
  }
  const result = await send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  const filePath = path.join(outputDir, name);
  await fs.writeFile(filePath, Buffer.from(result.data, "base64"));
  return filePath;
}

await Promise.all([
  send("Page.enable"),
  send("Runtime.enable"),
  send("Log.enable"),
  send("Network.enable"),
]);
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 1318,
  deviceScaleFactor: 1,
  mobile: false,
});
await send("Page.navigate", { url: appUrl });
await waitFor(
  `document.body?.innerText?.includes("MIS-OPC") && document.body?.innerText?.includes("Tổng quan")`,
  "Streamlit overview"
);

await evaluate(`(() => {
  const label = [...document.querySelectorAll("label")].find(
    (item) => item.innerText.includes("Chi tiết hợp đồng")
  );
  if (!label) return false;
  label.click();
  return true;
})()`);
await waitFor(
  `document.body?.innerText?.includes("Contract Detail") && document.body?.innerText?.includes("Duyệt AP-1")`,
  "contract detail"
);

const sidebarExpanded = await evaluate(`(() => {
  const sidebar = document.querySelector('[data-testid="stSidebar"]');
  if (sidebar && sidebar.getBoundingClientRect().width > 100) return true;
  const control = document.querySelector('[data-testid="stExpandSidebarButton"]')
    || document.querySelector('[data-testid="stSidebarCollapsedControl"] button')
    || document.querySelector('[data-testid="stSidebarCollapsedControl"]');
  if (!control) return false;
  control.click();
  return true;
})()`);
if (sidebarExpanded) {
  await new Promise((resolve) => setTimeout(resolve, 800));
}
await waitFor(
  `document.querySelector('[data-testid="stSidebar"]')?.getBoundingClientRect().width > 100`,
  "expanded sidebar"
);

const collapseTriggered = await evaluate(`(() => {
  const control = document.querySelector('[data-testid="stSidebarCollapseButton"] button')
    || document.querySelector('[data-testid="stSidebarCollapseButton"]');
  if (!control) return false;
  control.click();
  return true;
})()`);
if (!collapseTriggered) throw new Error("Sidebar collapse control was not clickable");
await waitFor(
  `(() => {
    const sidebar = document.querySelector('[data-testid="stSidebar"]');
    const sidebarRect = sidebar?.getBoundingClientRect();
    const control = document.querySelector('[data-testid="stExpandSidebarButton"]');
    if (!control) return false;
    const rect = control.getBoundingClientRect();
    const style = getComputedStyle(control);
    const sidebarIsOffCanvas = !sidebarRect || sidebarRect.right <= 1 || sidebarRect.width < 2;
    const controlIsOnCanvas = rect.left >= 0 && rect.top >= 0
      && rect.right <= window.innerWidth && rect.bottom <= window.innerHeight;
    return sidebarIsOffCanvas && controlIsOnCanvas
      && rect.width > 0 && rect.height > 0 && style.display !== "none"
      && style.visibility !== "hidden" && style.pointerEvents !== "none";
  })()`,
  "visible sidebar reopen control"
);
const collapsedSidebarScreenshot = await capture("implementation-sidebar-collapsed.png");
const sidebarToggle = await evaluate(`(() => {
  const control = document.querySelector('[data-testid="stExpandSidebarButton"]');
  const rect = control.getBoundingClientRect();
  const style = getComputedStyle(control);
  const result = {
    reopenVisible: rect.width > 0 && rect.height > 0,
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    display: style.display,
    visibility: style.visibility,
    pointerEvents: style.pointerEvents,
  };
  control.click();
  return result;
})()`);
await waitFor(
  `document.querySelector('[data-testid="stSidebar"]')?.getBoundingClientRect().width > 100`,
  "reopened sidebar"
);

const screenshots = [collapsedSidebarScreenshot];
screenshots.push(await capture("implementation-blocked-by-ap1.png"));
screenshots.push(await capture("implementation-blocked-by-ap1-full.png", true));

await clickButton("Duyệt AP-1");
await waitFor(
  `document.body?.innerText?.includes("CREDIT_PACKAGE_PROPOSED") && !document.body?.innerText?.includes("Thẻ quyết định đang bị khóa")`,
  "AP-1 approval"
);
screenshots.push(await capture("implementation-credit-package-proposed.png"));

await clickButton("Duyệt AP-2");
await waitFor(
  `![...document.querySelectorAll("button")].some((item) => item.innerText.trim() === "Duyệt AP-2")`,
  "AP-2 approval"
);
await clickButton("Duyệt AP-3");
await waitFor(
  `[...document.querySelectorAll("button")].some((item) => item.innerText.trim() === "Duyệt AP-4" && !item.disabled)`,
  "AP-3 approval"
);
await clickButton("Duyệt AP-4");
await waitFor(
  `document.querySelector('.state-pill')?.innerText.trim() === "DECISION_READY"
    && [...document.querySelectorAll("button")].some((item) => item.innerText.trim() === "Gọi Bank API mock")`,
  "AP-4 approval"
);
screenshots.push(await capture("implementation-decision-ready.png"));
screenshots.push(await capture("implementation-decision-ready-full.png", true));

await clickButton("Gọi Bank API mock");
await waitFor(
  `document.body?.innerText?.includes("Sandbox pre-check thành công")`,
  "Bank API success"
);

await clickButton("Phê duyệt");
await waitFor(
  `document.body?.innerText?.includes("state: ACTIVE")`,
  "final ACTIVE state"
);
screenshots.push(await capture("implementation-final-active.png"));
screenshots.push(await capture("implementation-final-active-full.png", true));

const viewport = await evaluate(`({
  width: window.innerWidth,
  height: window.innerHeight,
  devicePixelRatio: window.devicePixelRatio,
  scrollWidth: document.documentElement.scrollWidth,
  scrollHeight: document.documentElement.scrollHeight,
  sidebarVisible: Boolean(
    document.querySelector('[data-testid="stSidebar"]')
    && document.querySelector('[data-testid="stSidebar"]').getBoundingClientRect().width > 100
  )
})`);
const sidebarDiagnostics = await evaluate(`({
  testIds: [...document.querySelectorAll('[data-testid]')]
    .map((node) => node.getAttribute('data-testid'))
    .filter((value) => value && value.toLowerCase().includes('sidebar')),
  buttons: [...document.querySelectorAll('button')]
    .map((node) => ({ text: node.innerText.trim(), aria: node.getAttribute('aria-label'), title: node.getAttribute('title') }))
    .filter((item) => JSON.stringify(item).toLowerCase().includes('sidebar'))
})`);

const report = {
  appUrl,
  screenshots,
  viewport,
  sidebarToggle,
  sidebarDiagnostics,
  consoleErrors: [...new Set(consoleErrors)],
  pageErrors: [...new Set(pageErrors)],
  failedRequests: [...new Set(failedRequests)],
};
await fs.writeFile(
  path.join(outputDir, "browser-qa.json"),
  JSON.stringify(report, null, 2),
  "utf8"
);
socket.close();
console.log(JSON.stringify(report, null, 2));
