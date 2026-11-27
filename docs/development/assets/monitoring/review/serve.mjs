import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createRequire } from "node:module";

const root = fileURLToPath(new URL(".", import.meta.url));
const repo = resolve(root, "../../../../..");
const ui = resolve(repo, "ui");
const require = createRequire(resolve(ui, "package.json"));
const { createServer } = await import(require.resolve("vite"));
const { default: react } = await import(require.resolve("@vitejs/plugin-react"));
const { default: tailwind } = await import(require.resolve("@tailwindcss/vite"));
const dependencies = Object.keys(require("./package.json").dependencies);
const aliases = dependencies.map((name) => ({ find: name, replacement: resolve(ui, "node_modules", name) }));
const server = await createServer({
  configFile: false,
  root,
  plugins: [react(), tailwind()],
  resolve: { alias: [{ find: "@", replacement: resolve(ui, "src") }, ...aliases] },
  server: { host: "127.0.0.1", port: 8746, strictPort: true, fs: { allow: [repo] } },
});
await server.listen();
server.printUrls();
