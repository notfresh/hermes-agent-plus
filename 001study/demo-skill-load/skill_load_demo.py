#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skill_load_demo.py — Hermes 每轮对话开始时的 Skill 加载流程演示
================================================================

真实链路（每轮对话开始, 系统提示构建时）:

    AIAgent._build_system_prompt_parts()          run_agent.py:3810
      └─ build_system_prompt_parts(agent)         agent/system_prompt.py:147
           └─ build_skills_system_prompt(...)     agent/prompt_builder.py:1490
                ├─ Layer 1: 进程内 LRU 缓存        prompt_builder.py:1521
                ├─ Layer 2: 磁盘快照               prompt_builder.py:1346
                └─ Layer 3: 全量文件系统扫描        skill_utils.py:796 iter_skill_index_files
                     ├─ 解析 SKILL.md frontmatter  prompt_builder.py:1417 _parse_skill_file
                     ├─ 过滤: 平台/环境/禁用/条件    prompt_builder.py:1443 _skill_should_show
                     └─ 组装 <available_skills> 段  prompt_builder.py:1714
    模型看到索引后, 按需调 skill_view(name)        tools/skills_tool.py:961
      └─ 按名字找 SKILL.md                         tools/skill_manager_tool.py:605 _find_skill

三层缓存是核心思想: 索引内容取决于 (skills目录, 可用工具, 平台, 禁用列表),
全量扫描只在全部缓存失效时才发生 —— 这正是"每次对话都有 skill 索引、但不用
每次对话都重扫磁盘"的秘密。

跑:  python3 skill_load_demo.py
"""

import json
import os
import shutil
import tempfile
import time
from pathlib import Path

# 一个精简版 SKILL.md 生成器 -------------------------------------------------
def make_skill(skills_dir: Path, category: str, name: str, description: str,
               extra_frontmatter: str = "", body: str = "") -> Path:
    """在临时 skills 目录里造一个真实结构的 SKILL.md。"""
    d = skills_dir / category / name
    d.mkdir(parents=True, exist_ok=True)
    fm = f"""---
name: {name}
description: "{description}"
{extra_frontmatter}
---
"""
    body = body or f"# {name}\n\n这是 {name} 的教学示例内容。\n\n## 步骤\n1. 第一步\n2. 第二步\n"
    (d / "SKILL.md").write_text(fm + body, encoding="utf-8")
    return d / "SKILL.md"


# ── 复刻 prompt_builder.py 的过滤逻辑 (真实源码: prompt_builder.py:1443) ────

def skill_should_show(conditions: dict, available_toolsets: set) -> bool:
    """
    对照 prompt_builder.py:1443 _skill_should_show()
    - requires_toolsets: 声明需要的 toolset 不在场 → 隐藏
    - fallback_for_toolsets: 主 toolset 在场 → 隐藏 (备胎不需要出现)
    """
    ats = available_toolsets or set()
    for ts in conditions.get("requires_toolsets", []):
        if ts not in ats:
            return False, f"requires_toolsets={ts} 不在场"
    for ts in conditions.get("fallback_for_toolsets", []):
        if ts in ats:
            return False, f"fallback_for_toolsets={ts} 在场, 备胎隐藏"
    return True, ""


# ── 复刻 prompt_builder.py:1383 _build_snapshot_entry ───────────────────────

def build_snapshot_entry(skill_file: Path, skills_dir: Path, frontmatter: dict,
                         description: str) -> dict:
    """
    对照 prompt_builder.py:1383 _build_snapshot_entry()
    目录结构 → 元数据: 子目录名是 skill_name, 祖父目录是 category。
    如 skills/agent/skill-loading/SKILL.md → name=skill-loading, category=agent
    """
    rel = skill_file.relative_to(skills_dir)
    parts = rel.parts
    if len(parts) >= 2:
        skill_name = parts[-2]
        category = "/".join(parts[:-2]) if len(parts) > 2 else parts[0]
    else:
        category, skill_name = "general", skill_file.parent.name
    platforms = frontmatter.get("platforms") or []
    if isinstance(platforms, str):
        platforms = [platforms]
    return {
        "skill_name": skill_name,
        "category": category,
        "frontmatter_name": str(frontmatter.get("name", skill_name)),
        "description": description,
        "platforms": [str(p) for p in platforms],
        "conditions": frontmatter.get("conditions") or {},
    }


# ── 复刻 prompt_builder.py:1490 build_skills_system_prompt (三层缓存) ────────

class SkillIndexBuilder:
    """
    对照 prompt_builder.py:1490 build_skills_system_prompt()
    + prompt_builder.py:1521 (LRU) / 1346 (磁盘快照) / 1576 (全量扫描)
    """

    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.lru: dict = {}                       # Layer 1: 进程内缓存
        self.snapshot_path = skills_dir.parent / ".skills_prompt_snapshot.json"
        self.scan_count = 0                       # 统计全量扫描次数 (教学用)

    # -- Layer 2/3: 磁盘快照 ------------------------------------------------
    def _load_snapshot(self):
        """对照 prompt_builder.py:1346 _load_skills_snapshot()
        快照带 manifest (每个文件 mtime+size), 任何文件变了就整体失效。"""
        if not self.snapshot_path.exists():
            return None
        data = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        if self._manifest() != data.get("manifest"):
            print("  [快照] manifest 不匹配 (有 skill 被改过) -> 失效")
            return None
        return data

    def _write_snapshot(self, entries: list):
        """对照 prompt_builder.py:1609 _write_skills_snapshot()"""
        self.snapshot_path.write_text(
            json.dumps({"manifest": self._manifest(), "skills": entries},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    def _manifest(self) -> dict:
        """对照 prompt_builder.py:1330 附近 manifest 构建 (mtime_ns + size)。"""
        m = {}
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            st = f.stat()
            m[str(f.relative_to(self.skills_dir))] = [st.st_mtime_ns, st.st_size]
        return m

    # -- Layer 3: 全量扫描 --------------------------------------------------
    def _scan(self, available_toolsets: set) -> tuple:
        """
        对照 prompt_builder.py:1576 冷路径 + skill_utils.py:796 iter_skill_index_files
        用 os.walk(followlinks=True) 遍历 —— 注意: 会跟随 symlink!
        """
        print("  [扫描] 全量文件系统扫描开始 ...")
        self.scan_count += 1
        entries, by_cat = [], {}
        for root, dirs, files in os.walk(self.skills_dir, followlinks=True):
            if "SKILL.md" in files:
                skill_file = Path(root) / "SKILL.md"
                print(f"  [扫描] 发现 {skill_file.relative_to(self.skills_dir)}")
                frontmatter = self._parse_frontmatter(skill_file)
                # 平台过滤 (简化: 只认 linux)
                if frontmatter.get("platforms") and "linux" not in frontmatter["platforms"]:
                    print(f"    └ 过滤: platforms={frontmatter['platforms']} 不含 linux, 跳过")
                    continue
                desc = frontmatter.get("description", "")
                entry = build_snapshot_entry(skill_file, self.skills_dir, frontmatter, desc)
                ok, why = skill_should_show(entry["conditions"], available_toolsets)
                if not ok:
                    print(f"    └ 过滤: {why}, 跳过")
                    continue
                entries.append(entry)
                by_cat.setdefault(entry["category"], []).append(entry)
        self._write_snapshot(entries)
        return entries, by_cat

    def _parse_frontmatter(self, skill_file: Path) -> dict:
        """对照 prompt_builder.py:1417 _parse_skill_file (frontmatter 解析简化版)。"""
        raw = skill_file.read_text(encoding="utf-8")
        if not raw.startswith("---"):
            return {}
        end = raw.find("---", 3)
        fm = {}
        for line in raw[3:end].strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"')
        return fm

    # -- 对外主入口 ---------------------------------------------------------
    def build(self, available_toolsets: set) -> str:
        """
        对照 prompt_builder.py:1490 build_skills_system_prompt()
        顺序: LRU -> 快照 -> 全量扫描, 任何一层命中就不再往下走。
        """
        cache_key = (str(self.skills_dir), tuple(sorted(available_toolsets)))
        print(f"\n=== build_skills_system_prompt(toolsets={sorted(available_toolsets)}) ===")
        if cache_key in self.lru:                       # Layer 1
            print("  [L1] LRU 缓存命中, 直接返回 (不碰磁盘)")
            return self.lru[cache_key]
        print("  [L1] LRU 未命中")
        snapshot = self._load_snapshot()                # Layer 2
        if snapshot is not None:
            print("  [L2] 磁盘快照命中, 用快照组装 (不重扫磁盘)")
            by_cat = {}
            for e in snapshot["skills"]:
                by_cat.setdefault(e["category"], []).append(e)
        else:
            print("  [L2] 无有效快照")
            _, by_cat = self._scan(available_toolsets)  # Layer 3
        result = self._render(by_cat)
        self.lru[cache_key] = result                    # 回填 LRU
        return result

    def _render(self, by_cat: dict) -> str:
        """对照 prompt_builder.py:1692-1742 索引渲染 (available_skills 段)。"""
        lines = []
        for category in sorted(by_cat):
            lines.append(f"  {category}:")
            for e in sorted(by_cat[category], key=lambda x: x["skill_name"]):
                lines.append(f"    - {e['skill_name']}: {e['description']}")
        return (
            "## Skills (mandatory)\n"
            "Before replying, scan the skills below. If a skill matches or is even "
            "partially relevant to your task, you MUST load it with skill_view(name) "
            "and follow its instructions.\n\n"
            "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>"
        )


# ── 复刻 tools/skills_tool.py:961 skill_view (按需加载全文) ─────────────────

def skill_view(skills_dir: Path, name: str, method: str = "os_walk") -> str:
    """
    对照 tools/skills_tool.py:961 skill_view()
    模型看到索引后按名字加载全文。真实实现内部走 skill_manager_tool.py:605
    _find_skill —— 那里用的是 rglob("SKILL.md")。

    method 参数用来演示 #75130 的坑:
      - os_walk: 跟随 symlink, 能发现符号链接安装的 skill
      - rglob:   Path.rglob 不进入 symlink 目录, 发现不了
    """
    found = None
    if method == "os_walk":
        for root, dirs, files in os.walk(skills_dir, followlinks=True):
            if "SKILL.md" in files and Path(root).name == name:
                found = Path(root) / "SKILL.md"
                break
    else:  # 复刻 skill_manager_tool.py:617 的 rglob 行为
        for p in skills_dir.rglob("SKILL.md"):
            if p.parent.name == name:
                found = p
                break
    if found is None:
        return json.dumps({"success": False,
                           "error": f"Skill {name!r} not found ({method})"})
    return json.dumps({"success": True, "path": str(found),
                       "content": found.read_text(encoding="utf-8")[:120] + "..."},
                      ensure_ascii=False)


# ── 主流程 ------------------------------------------------------------------

def main():
    print("=" * 70)
    print("Hermes 对话开始时的 Skill 加载流程演示")
    print("(真实源码位置见每个函数 docstring, 汇总见同目录 README.md)")
    print("=" * 70)

    tmp = Path(tempfile.mkdtemp(prefix="skill-demo-"))
    skills_dir = tmp / "skills"
    try:
        # 造 4 个 skill: 正常 / 条件依赖 / 被禁用 / 平台不符
        make_skill(skills_dir, "agent", "skill-loading",
                   "了解 skill 加载机制的教学 skill")
        make_skill(skills_dir, "tools", "terminal-demo",
                   "需要 terminal 的 skill",
                   extra_frontmatter='conditions:\n  requires_toolsets: [terminal]')
        make_skill(skills_dir, "legacy", "old-demo",
                   "废弃 skill", extra_frontmatter="deprecated: true")
        make_skill(skills_dir, "win-only", "win-demo",
                   "Windows 专用", extra_frontmatter="platforms: [windows]")
        disabled = {"old-demo"}

        builder = SkillIndexBuilder(skills_dir)

        # 第 1 次: 冷启动 —— LRU 空 + 无快照 -> 全量扫描
        print("\n──── 第 1 次构建 (冷启动) ────")
        idx = builder.build({"terminal"})
        print(f"  [结果] 索引 {len(idx)} 字符, 全量扫描次数={builder.scan_count}")

        # 第 2 次: 同一会话内 —— LRU 命中, 零磁盘
        print("\n──── 第 2 次构建 (同一会话) ────")
        idx2 = builder.build({"terminal"})
        assert idx2 == idx
        print(f"  [结果] 索引 {len(idx2)} 字符 (与第1次完全一致), 全量扫描次数={builder.scan_count}")

        # 第 3 次: 新会话 (LRU 清空) —— 磁盘快照命中, 不重扫
        print("\n──── 第 3 次构建 (新会话, LRU 已清) ────")
        builder.lru.clear()
        idx3 = builder.build({"terminal"})
        assert idx3 == idx
        print(f"  [结果] 快照命中, 全量扫描次数={builder.scan_count} (没涨!)")

        # 第 4 次: skill 文件被改动 —— manifest 失效 -> 重新扫描
        print("\n──── 第 4 次构建 (某个 SKILL.md 被修改) ────")
        f = skills_dir / "agent" / "skill-loading" / "SKILL.md"
        text = f.read_text(encoding="utf-8")
        f.write_text(text + "\n# 新增内容\n", encoding="utf-8")
        builder.lru.clear()
        idx4 = builder.build({"terminal"})
        print(f"  [结果] 重扫完成, 全量扫描次数={builder.scan_count} (涨到 2)")

        # 第 5 步: 模型按需加载全文 (skill_view)
        print("\n──── 模型看到索引后, 调 skill_view('skill-loading') ────")
        print(" ", skill_view(skills_dir, "skill-loading")[:200])

        # 第 6 步: #75130 彩蛋 —— symlink 安装的 skill
        print("\n──── 彩蛋: symlink 安装的 skill (issue #75130) ────")
        ext = tmp / "ext"
        make_skill(ext, "custom", "linked-skill", "通过 symlink 安装的 skill")
        (skills_dir / "custom").mkdir(parents=True, exist_ok=True)
        os.symlink(ext / "custom" / "linked-skill", skills_dir / "custom" / "linked-skill",
                   target_is_directory=True)
        print("  用 os.walk(followlinks=True):",
              "找到" if '"success": true' in skill_view(skills_dir, "linked-skill", "os_walk") else "没找到")
        print("  用 rglob (skill_manager_tool._find_skill 的真实行为):",
              "找到" if '"success": true' in skill_view(skills_dir, "linked-skill", "rglob") else "没找到")
        print("  → 索引(iter_skill_index_files)能跟 symlink, 加载(_find_skill)跟不了,")
        print("    于是 symlink 装的 skill 显示在索引里但 skill_view 找不到 —— 这就是 #75130")

        # 展示最终索引长什么样
        print("\n──── 最终 <available_skills> 段 (模拟真实系统提示) ────")
        print(idx4)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
