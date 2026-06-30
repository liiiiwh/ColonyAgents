// 把命令行字符串切成参数数组，尊重单/双引号（修朴素 split(/\s+/) 拆坏带空格路径/引号参数的 bug）。
// 轻量 tokenizer：不处理转义反斜杠（MCP 命令行场景够用）。
export function splitArgs(input: string): string[] {
  const args: string[] = [];
  let cur = '';
  let quote: '"' | "'" | null = null;
  let has = false; // 当前是否在一个 token 内（区分空 token 与无 token）

  for (const ch of input) {
    if (quote) {
      if (ch === quote) quote = null;
      else cur += ch;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      has = true;
      continue;
    }
    if (ch === ' ' || ch === '\t' || ch === '\n') {
      if (has) {
        args.push(cur);
        cur = '';
        has = false;
      }
      continue;
    }
    cur += ch;
    has = true;
  }
  if (has) args.push(cur);
  return args;
}
