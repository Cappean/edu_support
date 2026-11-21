import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawn } from "node:child_process";

test("student selects identity, streams real order reply, and switches identity", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /今天有什么可以帮你/ }),
  ).toBeVisible();
  const selector = page.getByLabel("选择演示学员");
  await expect(selector.locator("option")).not.toHaveCount(1);
  const accounts = await selector
    .locator("option")
    .evaluateAll((options) =>
      options.map((o) => (o as HTMLOptionElement).value).filter(Boolean),
    );
  await selector.selectOption(accounts[0]);
  await page.getByRole("button", { name: /订单查询/ }).click();
  await expect(page.locator(".message.assistant").last()).toContainText("ORD", {
    timeout: 110000,
  });
  await expect(page.locator(".thinking")).toHaveCount(0, { timeout: 110000 });
  await page.screenshot({
    path: "../.runtime/student-desktop.png",
    fullPage: true,
  });
  await selector.selectOption(accounts[1]);
  await expect(page.locator(".message")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: /今天有什么可以帮你/ }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("administrator queries data and edits knowledge through real APIs", async ({
  page,
}) => {
  const password =
    process.env.ADMIN_PASSWORD ||
    readFileSync(resolve("../.runtime/admin-password.txt"), "utf8").trim();
  await page.goto("/admin");
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: /登录工作台/ }).click();
  await expect(page.getByRole("heading", { name: "工作概览" })).toBeVisible();
  await page.getByRole("button", { name: "订单查询", exact: true }).click();
  await expect(page.locator("tbody tr").first()).toBeVisible();
  await page.getByRole("button", { name: "知识内容", exact: true }).click();
  await page.getByRole("button", { name: "新增内容" }).click();
  const title = "浏览器验收草稿" + Date.now();
  await page.getByLabel("问题标题").fill(title);
  await page.getByLabel("正文").fill("这是浏览器验收专用草稿，验证后删除。");
  await page.getByRole("button", { name: "保存内容" }).click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByRole("heading", { name: title }).click();
  await page.getByRole("button", { name: "删除草稿" }).click();
  await expect(page.getByRole("heading", { name: title })).toHaveCount(0);
  await page.screenshot({
    path: "../.runtime/admin-desktop.png",
    fullPage: true,
  });
});

test("mobile chat layout fits viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByLabel("选择演示学员")).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth),
  ).toBeLessThanOrEqual(390);
  await page.screenshot({
    path: "../.runtime/student-mobile.png",
    fullPage: true,
  });
});

test("slower prior identity response cannot overwrite the latest selection", async ({
  page,
}) => {
  await page.goto("/");
  const selector = page.getByLabel("选择演示学员");
  await expect(selector.locator("option")).not.toHaveCount(1);
  const accounts = await selector
    .locator("option")
    .evaluateAll((options) =>
      options.map((o) => (o as HTMLOptionElement).value).filter(Boolean),
    );
  await page.route("**/api/v1/auth/demo", async (route) => {
    const response = await route.fetch();
    if (route.request().postDataJSON().user_id === Number(accounts[0]))
      await new Promise((r) => setTimeout(r, 1000));
    await route.fulfill({ response });
  });
  await selector.selectOption(accounts[0]);
  await selector.selectOption(accounts[1]);
  await expect(selector).toHaveValue(accounts[1]);
  await page.waitForTimeout(1200);
  await expect(selector).toHaveValue(accounts[1]);
});

test("administrator approves refund and closes ticket, student sees both results", async ({
  page,
  context,
}) => {
  const fixture = spawn(
    resolve("../.runtime/venv/Scripts/python.exe"),
    [resolve("../scripts/e2e_business_fixture.py")],
    { cwd: resolve(".."), stdio: ["pipe", "pipe", "pipe"] },
  );
  const data: any = await new Promise((accept, reject) => {
    let buffer = "";
    fixture.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      if (buffer.includes("\n")) {
        try {
          accept(JSON.parse(buffer.split("\n")[0]));
        } catch (error) {
          reject(error);
        }
      }
    });
    fixture.on("exit", (code) => {
      if (!buffer) reject(new Error("fixture exited " + code));
    });
    fixture.stderr.on("data", (chunk) => {
      console.error("fixture error", chunk.toString());
    });
  });
  try {
    const password =
      process.env.ADMIN_PASSWORD ||
      readFileSync(resolve("../.runtime/admin-password.txt"), "utf8").trim();
    await page.goto("/admin");
    await page.getByLabel("密码", { exact: true }).fill(password);
    await page.getByRole("button", { name: /登录工作台/ }).click();
    await page.getByRole("button", { name: "退款审批", exact: true }).click();
    await page.getByLabel("搜索", { exact: true }).fill(data.refund.number);
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: /查看详情/ }).click();
    await page.getByLabel("审批说明").fill("浏览器验收：同意全额退款");
    await page.getByRole("button", { name: "通过并模拟退款" }).click();
    await expect(page.locator("tbody")).toContainText("已退款");
    await page.getByRole("button", { name: "问题工单", exact: true }).click();
    await page.getByLabel("搜索", { exact: true }).fill(data.title);
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: /查看详情/ }).click();
    await page
      .getByLabel("回复或处理结果")
      .fill("目录服务已恢复，请刷新后重试。");
    await page.getByRole("button", { name: "回复并结单" }).click();
    await expect(page.locator("tbody")).toContainText("已结单");
    const student = await context.newPage();
    await student.goto("/");
    await student.getByLabel("选择演示学员").selectOption(String(data.user_id));
    await student
      .getByRole("button", { name: "退款进度", exact: true })
      .click();
    await expect(
      student.locator(".record-card").filter({ hasText: data.refund.number }),
    ).toContainText("已退款");
    await student.locator(".drawer .icon-button").click();
    await student
      .getByRole("button", { name: "我的工单", exact: true })
      .click();
    await student.getByRole("heading", { name: data.title }).click();
    await expect(student.locator(".drawer")).toContainText(
      "目录服务已恢复，请刷新后重试。",
    );
    await expect(student.locator(".drawer .badge")).toContainText("已结单");
    await student.close();
  } finally {
    fixture.stdin.write("\n");
    fixture.stdin.end();
    await new Promise((resolve) => fixture.on("exit", resolve));
  }
});
