# 代码示例与坑

## 发现与绑定

```js
const st = await cua.getState();
// st.browsers[] 里找到 Chrome（type: "extension"）的 tabs
const tab = await cua.getTab("808367484", { browser: "3" }); // tabId, browserId
```

## 复用标签页搜索并抽取（SPA）

```js
async function searchAndExtract(q) {
  await tab.goto("https://www.goofish.com/search?q=" + encodeURIComponent(q));
  await tab.playwright.waitForTimeout(3000); // SPA 异步渲染，networkidle 可能提前返回
  return await tab.playwright.evaluate(() =>
    Array.from(document.querySelectorAll('a[href*="/item"]')).map(a => ({
      h: a.href,
      t: (a.innerText || '').replace(/\s+/g, ' ').trim()
    })).filter(x => x.t.length > 4)
  );
}
```

结果先 `nodeRepl.write(JSON.stringify(data))` 核对，再用 `apply_patch` 写成本地 JSON 文件。

## 常见坑

- `evaluate` 运行在只读沙箱里，`decodeURIComponent` 等全局可能不存在；脚本里只返回 `location.href` 或原始文本，解析放到外部。
- SPA 列表异步加载：`waitForLoadState("networkidle")` 可能过早返回，补 `waitForTimeout`；必要时滚动触发懒加载。
- 不同分类的搜索结果 DOM 可能不同：有的用 `a[href*="/item"]`，有的不用，过滤条件别写死；先抽样看 `document.querySelectorAll('a')` 里的文本与 href。
- 绑定后 AX/元素索引会随页面刷新失效；交互优先用 Playwright locator，而不是固定索引。
- REPL 里 `const` 句柄跨调用持久；不要重复 `getTab` / `getBrowser`，除非句柄失效。

## browser-use CLI 作为备选

若改用 CLI：`browser-use connect` 需要 Chrome 已开启远程调试；失败时给用户二选一（开启远程调试 / 用 `--profile` 托管 Chromium）。能用 `cua` 接管已有标签页时优先 `cua`。
