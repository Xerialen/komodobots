import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served at http://192.168.86.33:8095/botlab/ (LD-A2 deploys dist/ there).
// base makes the build fully self-contained under /botlab/ — no hashed chunks
// leak into the shared web/assets/ like the old local-hub deploy did.
export default defineConfig({
  base: "/botlab/",
  plugins: [react()],
});
