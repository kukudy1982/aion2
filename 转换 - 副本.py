#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AION 综合转换工具 v5.5  终极修复版
适配 CSV：
  aion-物料.csv : 原料名称,制作职业,来源,单价
  bom.csv       : 制作职业,名称,需求等级,计算系数,材料1,数量1,...,材料9,数量9
"""
import sys, subprocess, json, re, traceback, os, importlib
# ↓↓ 修复：显式导入 importlib.util
import importlib.util
from pathlib import Path
from collections import defaultdict, deque

# --------------------  依赖自检（终极修复）  --------------------
def check_and_install():
    """检查并安装依赖，修复了 importlib.util 的兼容性问题"""
    print("\n[🔍] 检查运行环境...")
    required = {'pandas': 'pandas', 'chardet': 'chardet'}
    missing = []
    
    for mod, pip in required.items():
        # 正确的检测方式，兼容所有Python版本
        if importlib.util.find_spec(mod) is None:
            missing.append(pip)
            print(f"[✗] 缺失依赖: {mod}")
        else:
            print(f"[✓] 依赖正常: {mod}")
    
    if missing:
        print(f"\n[⚠] 发现 {len(missing)} 个缺失依赖，正在自动安装...")
        cmd = [sys.executable, '-m', 'pip', 'install', *missing]
        print(f"    执行: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                print("[✓] 依赖安装成功！")
                print("    请重新运行此脚本")
                input("\n按 Enter 退出...")
                sys.exit(0)
            else:
                print(f"[✗] 安装失败 (返回码: {result.returncode})")
                print("    错误信息:", result.stderr)
                input("\n按 Enter 退出...")
                sys.exit(1)
        except Exception as e:
            print(f"[✗] 安装时出错: {e}")
            print("    请手动执行: pip install " + " ".join(missing))
            input("\n按 Enter 退出...")
            sys.exit(1)
    else:
        print("[✓] 所有依赖已就绪！")

# 强制在脚本所在目录运行，防止路径问题
os.chdir(os.path.dirname(os.path.abspath(__file__)))
print(f"[📁] 当前工作目录: {Path.cwd()}")

# 检查依赖（必须先执行，再导入模块）
check_and_install()

# 现在安全地导入模块
import pandas as pd
import chardet

# --------------------  配置  --------------------
CFG = {
    "MATERIAL_CSV": "aion-物料.csv",
    "BOM_CSV":      "bom.csv",
    "HTML_OUT":     "index_generated.html"
}

# --------------------  工具函数  --------------------
def detect_encoding(p: Path) -> str:
    print(f"[📖] 检测编码: {p.name}")
    enc = chardet.detect(p.read_bytes())['encoding'] or 'utf-8'
    print(f"[✓] 编码: {enc}")
    return enc

def safe_int(v, d=0):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return d

def parse_level(s):
    m = re.fullmatch(r'(\D+)(\d+)', str(s).strip())
    return (m.group(1), int(m.group(2))) if m else (str(s).strip(), 0)

# --------------------  拓扑排序（防循环依赖）  --------------------
def topological_sort(df: pd.DataFrame):
    print("[🔀] 开始拓扑排序...")
    graph, reverse, nodes = defaultdict(list), defaultdict(list), set()
    for _, r in df.iterrows():
        prod = str(r.get('名称', '')).strip()
        if not prod:
            continue
        nodes.add(prod)
        for i in range(1, 10):
            m = str(r.get(f'材料{i}', '')).strip()
            if m:
                nodes.add(m)
                graph[prod].append(m)
                reverse[m].append(prod)
    in_deg = {n: 0 for n in nodes}
    for vs in graph.values():
        for v in vs:
            in_deg[v] += 1
    q = deque([n for n, d in in_deg.items() if d == 0])
    out = []
    while q:
        cur = q.popleft()
        if cur in df['名称'].values:
            out.append(cur)
        for d in reverse[cur]:
            in_deg[d] -= 1
            if in_deg[d] == 0:
                q.append(d)
    exist = set(out)
    for _, r in df.iterrows():
        name = str(r.get('名称', '')).strip()
        if name and name not in exist:
            out.append(name)
    name2idx = {str(r['名称']).strip(): i for i, r in df.iterrows() if str(r.get('名称', '')).strip()}
    sorted_idx = [name2idx[n] for n in out if n in name2idx]
    print(f"[✓] 拓扑排序完成，共 {len(sorted_idx)} 个产品")
    return sorted_idx

# --------------------  物料 CSV → JSON  --------------------
def convert_material():
    print("\n" + "="*60)
    print("[步骤1] 物料CSV → JSON")
    print("="*60)
    
    p = Path(CFG["MATERIAL_CSV"])
    if not p.exists():
        print(f"[✗] 文件不存在: {p.resolve()}")
        print("提示: 请确保CSV文件与脚本在同一目录")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    enc = detect_encoding(p)
    try:
        df = pd.read_csv(p, encoding=enc, keep_default_na=False)
        print(f"[✓] 成功读取 {len(df)} 行数据")
    except Exception as e:
        print(f"[✗] 读取失败: {e}")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    need = {'原料名称', '制作职业', '来源', '单价'}
    if (miss := need - set(df.columns)):
        print(f"[✗] 缺少必要列: {miss}")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    items = []
    for idx, r in df.iterrows():
        name = str(r.get('原料名称', '')).strip()
        if not name:
            continue
        # ========== 核心修复：将 split(',') 改为 split('/') ==========
        # 注意：此处为物料名中的斜杠分隔，用于支持天魔两族名称
        items.append({
            "id": f"M{idx+1:03d}",
            "name": name,
            "professions": [p.strip() for p in str(r.get('制作职业', '')).split('/') if p.strip()],
            "source": str(r.get('来源', '未知')).strip() or '未知',
            "price": safe_int(r.get('单价', 0))
        })
    
    print(f"[✓] 物料记录: {len(items)}")
    return items

# --------------------  BOM CSV → Recipe JSON  --------------------
def convert_bom(base_map):
    print("\n" + "="*60)
    print("[步骤2] BOM → Recipe JSON")
    print("="*60)
    
    p = Path(CFG["BOM_CSV"])
    if not p.exists():
        print(f"[✗] 文件不存在: {p.resolve()}")
        print("提示: 请确保CSV文件与脚本在同一目录")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    enc = detect_encoding(p)
    try:
        df = pd.read_csv(p, encoding=enc, keep_default_na=False)
        print(f"[✓] 成功读取 {len(df)} 行数据")
    except Exception as e:
        print(f"[✗] 读取失败: {e}")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    need = {'制作职业', '名称', '需求等级', '计算系数'}
    for i in range(1, 10):
        need.update({f'材料{i}', f'数量{i}'})
    if (miss := need - set(df.columns)):
        print(f"[✗] 缺少必要列: {miss}")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    # 预生成编码
    name2id = base_map.copy()
    all_prod = set(df['名称'].astype(str).str.strip().tolist())
    for idx, r in df.iterrows():
        name = str(r.get('名称', '')).strip()
        if name and name not in name2id:
            name2id[name] = f"COMP{len(name2id):04d}"
    
    # 拓扑排序
    sorted_idx = topological_sort(df)
    recipes = {}
    for idx in sorted_idx:
        r = df.iloc[idx]
        name = str(r.get('名称', '')).strip()
        if not name:
            continue
        
        mats = []
        for i in range(1, 10):
            m_name = str(r.get(f'材料{i}', '')).strip()
            qty = safe_int(r.get(f'数量{i}', '0'), 0)
            if not m_name or qty <= 0:
                continue
            
            # 自动补全缺失编码
            if m_name not in name2id:
                name2id[m_name] = f"COMP{len(name2id):04d}" if m_name in all_prod else m_name
            
            mid = name2id[m_name]
            if m_name in all_prod:
                mats.append({"ref": mid, "qty": qty, "name": m_name})
            else:
                mats.append({"id": mid, "qty": qty, "name": m_name})
        
        lvl_str = str(r.get('需求等级', '')).strip()
        lvl, lvl_num = parse_level(lvl_str)
        recipes[name2id[name]] = {
            "id": name2id[name],
            "name": name,
            "level": lvl_str,
            "levelNum": lvl_num,
            "profession": str(r.get('制作职业', '')).strip(),
            "calculation_coefficient": safe_int(r.get('计算系数', 1), 1) or 1,
            "materials": mats
        }
    
    print(f"[✓] 配方记录: {len(recipes)}")
    return recipes, name2id

# --------------------  HTML 模板（完整，修复职业筛选）  --------------------
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>永恒之塔2 制作成本计算器</title>
<style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'SF Pro Text', 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #f5f7fa 0%, #e9ecef 100%);
            min-height: 100vh;
            padding: 15px;
            font-size: 14px;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
            overflow-x: hidden;
        }

        @media (max-width: 768px) {
            body {
                padding: 10px;
                font-size: 13px;
            }
        }

        .container {
            display: flex;
            gap: 20px;
            max-width: 1600px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.8);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.08);
            overflow: hidden;
            min-height: calc(100vh - 30px);
            border: 1px solid rgba(255, 255, 255, 0.5);
        }

        @media (max-width: 768px) {
            .container {
                flex-direction: column;
                gap: 15px;
                min-height: calc(100vh - 20px);
                border-radius: 16px;
            }
        }

        .material-panel {
            flex: 1.2;
            background: rgba(248, 249, 250, 0.6);
            padding: 25px;
            overflow-y: auto;
            min-width: 500px;
        }

        @media (max-width: 768px) {
            .material-panel {
                min-width: auto;
                padding: 18px;
                max-height: 50vh;
            }
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        h2 {
            color: #1d1d1f;
            font-size: 24px;
            font-weight: 600;
            letter-spacing: -0.5px;
        }

        @media (max-width: 768px) {
            h2 {
                font-size: 20px;
            }
        }

        table {
            width: 100%;
            border-collapse: separate;
            border-spacing: 0;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
            table-layout: fixed;
        }

        @media (max-width: 768px) {
            table {
                display: block;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            thead, tbody {
                display: table;
                width: 100%;
                min-width: 400px;
            }
        }

        th, td {
            padding: 14px 16px;
            text-align: left;
            border-bottom: 1px solid #f0f0f0;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        @media (max-width: 768px) {
            th, td {
                padding: 12px 14px;
                font-size: 12px;
            }
        }

        th {
            background: #007AFF;
            color: white;
            font-weight: 500;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        th:nth-child(1) { width: 200px; }
        th:nth-child(2) { width: 100px; }
        th:nth-child(3) { width: 120px; }

        @media (max-width: 768px) {
            th:nth-child(1) { width: 150px; }
            th:nth-child(2) { width: 80px; }
            th:nth-child(3) { width: 100px; }
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover {
            background: #f8f9fa;
        }

        tr.highlighted {
            background: #fff8e1 !important;
            transition: background-color 0.3s ease;
        }

        td[contenteditable="true"] {
            cursor: text;
            transition: background 0.2s;
            color: #1d1d1f;
            user-select: text;
        }

        @media (max-width: 768px) {
            td[contenteditable="true"] {
                min-height: 44px;
                display: inline-flex;
                align-items: center;
            }
        }

        td[contenteditable="true"]:hover {
            background: #f0f7ff;
        }

        td[contenteditable="true"]:focus {
            outline: none;
            background: #ffffff;
            box-shadow: inset 0 0 0 2px #007AFF;
        }

        .stats {
            margin-top: 20px;
            padding: 16px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 12px;
            text-align: center;
            color: #86868b;
            font-size: 14px;
            font-weight: 500;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }

        @media (max-width: 768px) {
            .stats {
                font-size: 13px;
                padding: 14px;
                margin-top: 15px;
            }
        }

        .profession-filter {
            margin-bottom: 20px;
            padding: 16px;
            background: rgba(0, 122, 255, 0.08);
            border-radius: 12px;
            display: flex;
            align-items: center;
            gap: 12px;
            transition: all 0.3s ease;
        }

        @media (max-width: 768px) {
            .profession-filter {
                flex-wrap: wrap;
                padding: 14px;
                gap: 10px;
            }
        }

        .profession-filter label {
            font-weight: 500;
            color: #007AFF;
            font-size: 14px;
            white-space: nowrap;
        }

        .profession-filter select {
            padding: 10px 16px;
            border: 1px solid #d1d1d6;
            border-radius: 10px;
            font-size: 14px;
            background: rgba(255, 255, 255, 0.9);
            cursor: pointer;
            min-width: 140px;
            color: #1d1d1f;
            transition: all 0.2s;
            appearance: none;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2386868b' d='M6 9L1 4h10z'/%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 12px center;
            padding-right: 32px;
        }

        @media (max-width: 768px) {
            .profession-filter select {
                min-width: 120px;
                padding: 8px 12px;
                font-size: 13px;
            }
        }

        .product-panel {
            flex: 1;
            padding: 25px;
            overflow-y: auto;
            min-width: 700px;
        }

        @media (max-width: 768px) {
            .product-panel {
                min-width: auto;
                padding: 18px;
                overflow-y: visible;
            }
        }

        .product-selector {
            margin-bottom: 25px;
        }

        .product-selector-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }

        .product-selector-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .clear-btn {
            width: 32px;
            height: 32px;
            background: #007AFF;
            border: none;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1);
            box-shadow: 0 4px 12px rgba(0, 122, 255, 0.3);
        }

        @media (max-width: 768px) {
            .clear-btn {
                width: 36px;
                height: 36px;
            }
        }

        .clear-btn:hover {
            background: #0051d5;
            transform: scale(1.1);
            box-shadow: 0 6px 20px rgba(0, 122, 255, 0.4);
        }

        .clear-btn:active {
            transform: scale(0.95);
        }

        .clear-btn svg {
            width: 18px;
            height: 18px;
            fill: white;
            transition: transform 0.3s;
        }

        .searchable-select {
            position: relative;
        }

        .search-input {
            width: 100%;
            padding: 14px 18px;
            border: 1px solid #d1d1d6;
            border-radius: 12px;
            font-size: 16px;
            transition: all 0.3s;
            cursor: pointer;
            background: rgba(255, 255, 255, 0.9);
            color: #1d1d1f;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
        }

        @media (max-width: 768px) {
            .search-input {
                font-size: 15px;
                padding: 16px 18px;
                border-radius: 14px;
            }
        }

        .search-input:focus {
            outline: none;
            border-color: #007AFF;
            box-shadow: 0 0 0 3px rgba(0, 122, 255, 0.2), 0 4px 12px rgba(0, 0, 0, 0.08);
        }

        .dropdown {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border: 1px solid #e5e5ea;
            border-top: none;
            max-height: 320px;
            overflow-y: auto;
            z-index: 1000;
            display: none;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.12);
            border-radius: 0 0 12px 12px;
            margin-top: -8px;
            padding-top: 8px;
        }

        .dropdown-item {
            padding: 14px 18px;
            cursor: pointer;
            transition: background 0.2s;
            border-bottom: 1px solid #f2f2f7;
            white-space: nowrap;
            color: #1d1d1f;
        }

        .dropdown-item:hover {
            background: rgba(0, 122, 255, 0.05);
        }

        .dropdown-item:last-child {
            border-bottom: none;
        }

        .success-rate-container {
            margin-top: 20px;
            padding: 16px;
            background: rgba(255, 149, 0, 0.08);
            border-radius: 12px;
        }

        .success-rate-row {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
        }

        .success-rate-checkbox {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }

        .success-rate-label {
            font-weight: 500;
            color: #ff9500;
            font-size: 14px;
            cursor: pointer;
        }

        .success-rate-input-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: 30px;
        }

        .success-rate-input {
            width: 70px;
            padding: 8px 12px;
            border: 1px solid #d1d1d6;
            border-radius: 8px;
            font-size: 14px;
            text-align: center;
            color: #1d1d1f;
        }

        .success-rate-input:disabled {
            background: #f0f0f0;
            color: #86868b;
            cursor: not-allowed;
        }

        .success-rate-input:focus {
            outline: none;
            border-color: #ff9500;
        }

        .percent-label {
            color: #86868b;
            font-size: 14px;
        }

        .material-multiplier {
            margin-top: 8px;
            padding: 10px;
            background: rgba(0, 122, 255, 0.05);
            border-radius: 10px;
            text-align: center;
            color: #007AFF;
            font-weight: 600;
            font-size: 14px;
        }

        .combo-warning {
            margin-top: 8px;
            padding: 10px;
            background: rgba(255, 59, 48, 0.05);
            border-radius: 10px;
            color: #ff3b30;
            font-size: 13px;
            font-weight: 500;
        }

        .cost-result {
            background: linear-gradient(135deg, #007AFF 0%, #5856d6 100%);
            color: white;
            padding: 25px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0, 122, 255, 0.3);
        }

        @media (max-width: 768px) {
            .cost-result {
                padding: 20px;
                border-radius: 14px;
            }
        }

        .total-cost {
            text-align: center;
            margin-bottom: 25px;
        }

        .cost-value {
            font-size: 42px;
            font-weight: 700;
            color: #fff;
            text-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
        }

        @media (max-width: 768px) {
            .cost-value {
                font-size: 36px;
            }
        }

        .cost-details {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 12px;
            padding: 20px;
            max-height: 320px;
            overflow-y: auto;
        }

        .detail-row {
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
            font-size: 15px;
        }

        .detail-row:last-child {
            border-bottom: none;
        }

        .export-btn {
            margin-top: 20px;
            width: 100%;
            padding: 14px;
            background: rgba(255, 255, 255, 0.25);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.4);
            border-radius: 12px;
            cursor: pointer;
            font-size: 15px;
            font-weight: 500;
            transition: all 0.3s;
        }

        .export-btn:hover {
            background: rgba(255, 255, 255, 0.35);
        }

        .instructions {
            margin-bottom: 20px;
            padding: 20px;
            background: rgba(0, 122, 255, 0.05);
            border-radius: 12px;
            color: #007AFF;
            font-size: 14px;
            line-height: 1.6;
        }

        @media (max-width: 768px) {
            .instructions {
                padding: 16px;
                font-size: 13px;
            }
        }

        .server-info {
            font-size: 14px;
            font-weight: 600;
            color: #ff3b30;
            margin-top: 10px;
            text-align: left;
        }

        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }

        ::-webkit-scrollbar-thumb {
            background: #c6c6c8;
            border-radius: 3px;
        }

        @media (max-width: 768px) {
            * {
                touch-action: manipulation;
            }
        }

        @media (hover: none) {
            .clear-btn:active {
                background: #0051d5;
                transform: scale(0.95);
            }
            
            .export-btn:active {
                background: rgba(255, 255, 255, 0.35);
            }
        }

        .coefficient-tag {
            background: rgba(255, 149, 0, 0.15);
            color: #ff9500;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            margin-left: 8px;
        }

        /* BOM树样式 - 缩进优化 */
        .tree-node {
            margin-left: 12px;  /* 缩进12px */
            border-left: 1px solid #e5e5ea;
            padding-left: 8px;
            margin-top: 6px;
        }

        @media (max-width: 768px) {
            .tree-node {
                margin-left: 10px;
                padding-left: 6px;
            }
        }

        .tree-root {
            margin-left: 0;
            border-left: none;
            padding-left: 0;
        }

        .node-header {
            display: flex;
            align-items: center;
            padding: 12px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }

        @media (max-width: 768px) {
            .node-header {
                padding: 10px;
            }
        }

        .toggle-btn {
            width: 24px;
            height: 24px;
            margin-right: 10px;
            background: #e5e5ea;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 14px;
            transition: all 0.2s;
            flex-shrink: 0;
            color: #86868b;
        }

        .toggle-btn:hover {
            background: #d1d1d6;
        }

        .children {
            display: none;
        }

        .children.expanded {
            display: block;
        }

        /* 用量/价格信息样式 */
        .material-info {
            display: flex;
            gap: 10px;
            font-size: 13px;
            color: #86868b;
            flex-shrink: 0;
            white-space: nowrap;
        }

        .qty-info {
            color: #007AFF;
            font-weight: 600;
        }

        .price-info {
            color: #ff9500;
            font-weight: 600;
        }

        .subtotal-info {
            color: #5856d6;
            font-weight: 700;
        }
</style>
</head>
<body>
<div class="container">
  <div class="material-panel">
    <div class="instructions">
      <h4>🎮 使用说明</h4>
      <ul>
        <li>在左侧表格中编辑<strong>当前交易行物价</strong></li>
        <li>黄色高亮：<strong>当前配方使用的物料</strong></li>
        <li>商店价格自动固定，<strong>无需手动输入</strong></li>
        <li>支持实时计算，<strong>修改价格立即更新成本</strong></li>
      </ul>
      <div class="server-info">巨响的炮弹 纳尼亚 霜降Frost</div>
    </div>

<div class="panel-header"><h2>基础物料物价表</h2></div>
    
    <div class="profession-filter" style="justify-content: flex-start; gap: 24px;">
      <div class="race-selector-container" style="display: flex; align-items: center; gap: 12px;">
          <label for="race-selector">种族版本选择：</label>
          <select id="race-selector">
              <option value="T" selected>天族</option>
              <option value="M">魔族</option>
          </select>
      </div>
      <div class="profession-filter-inner" style="display: flex; align-items: center; gap: 12px;">
          <label>制作职业筛选：</label>
          <select id="professionSelect"></select>
      </div>
    </div>
    
    <table id="materialTable"><thead><tr>

    <table id="materialTable"><thead><tr>
      <th>物料名称</th><th>来源</th><th>单价(金币)</th>
    </tr></thead><tbody id="materialTableBody"></tbody></table>
    <div class="stats" id="materialStats">使用到的物料：0 / 0</div>
  </div>

  <div class="product-panel">
    <div class="product-selector">
      <div class="product-selector-header">
        <div class="product-selector-title">
          <h2>产品选择</h2>
          <button class="clear-btn" id="clearProductBtn" onclick="clearProductSelection()" title="清空选择"><svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></button>
        </div>
      </div>
      <div class="searchable-select">
        <input type="text" class="search-input" id="productSearch" placeholder="点击选择产品或输入名称/编号搜索...">
        <div class="dropdown" id="productDropdown"></div>
      </div>
      <div class="success-rate-container">
        <div class="success-rate-row">
          <input type="checkbox" class="success-rate-checkbox" id="instantSuccessCheckbox" checked>
          <label class="success-rate-label" for="instantSuccessCheckbox">一次性成功</label>
        </div>
        <div class="success-rate-input-wrapper">
          <input type="number" class="success-rate-input" id="successRateInput" min="1" max="100" value="100" disabled>
          <span class="percent-label">%</span>
        </div>
        <div class="material-multiplier" id="materialMultiplier">成功率系数：1.00x</div>
        <div class="combo-warning">注意：成功率越低，所需材料越多（100%/成功率=材料倍数）</div>
      </div>
    </div>

    <div class="cost-result">
      <div class="total-cost">
        <h3>产品制作成本</h3>
        <div class="cost-value" id="totalCost">0</div>
      </div>
      <div class="cost-details" id="costDetails">
        <h4 style="margin-bottom:15px;font-size:16px;font-weight:600">成本构成明细</h4>
        <div id="costDetailsBody">请选择产品查看明细</div>
      </div>
      <button class="export-btn" onclick="exportCostReport()">📄 导出成本报告</button>
    </div>

    <div class="bom-panel">
      <h3>产品结构BOM</h3>
      <div id="treeContainer">请选择产品</div>
    </div>
  </div>
</div>

<script>
// ====================  数据注入  ====================
const RAW_MATERIALS = [
/*AUTO_GENERATED_MATERIALS*/
];
const PRODUCT_BOM = {
/*AUTO_GENERATED_RECIPES*/
};
// ====================  全局变量  ====================
const ALL_MATERIALS_MAP = {};
RAW_MATERIALS.forEach(m => ALL_MATERIALS_MAP[m.id] = m);
let currentRace = 'T'; // 新增：全局种族状态，默认天族
let currentProfession = 'all';
let currentProduct = null;
let currentSuccessRate = 100;
let isInstantSuccess = true;

/**
 * 新增：根据当前种族选择，解析物料/产品名称。
 * 名称格式: "天族名称/魔族名称" 或 "通用名称"
 * @param {string} rawName 原始名称字符串
 * @param {string} race 'T' (天族) 或 'M' (魔族)
 * @returns {string} 对应的种族名称
 */
function getLocalizedName(rawName, race) {
    if (typeof rawName !== 'string') return rawName;
    const parts = rawName.split('/', 2);
    if (parts.length === 2) {
        // T: 天族 (在 / 前), M: 魔族 (在 / 后)
        return (race === 'T' ? parts[0] : parts[1]).trim();
    }
    return rawName.trim(); // 通用名称
}

// ====================  成功率控制  ====================
function updateSuccessRate(rate) {
  rate = Math.max(1, Math.min(100, rate));
  currentSuccessRate = rate;
  document.getElementById('successRateInput').value = rate;
  const mult = (100 / rate).toFixed(2);
  document.getElementById('materialMultiplier').textContent = `成功率系数：${mult}x`;
  if (currentProduct) {
    calculateAndDisplayCost(currentProduct.id);
    generateBOMTree(currentProduct.id);
  }
}
function toggleInstantSuccess(checked) {
  isInstantSuccess = checked;
  const inp = document.getElementById('successRateInput');
  if (checked) {
    inp.disabled = true;
    inp.value = 100;
    updateSuccessRate(100);
  } else {
    inp.disabled = false;
    updateSuccessRate(parseInt(inp.value) || 25);
  }
}

// ====================  职业筛选（仅来自 BOM）  ====================
function initProfessionFilter() {
  const sel = document.getElementById('professionSelect');
  sel.innerHTML = '<option value="all">全部职业</option>';
  const professions = new Set();
  Object.values(PRODUCT_BOM).forEach(p => professions.add(p.profession));
  Array.from(professions).sort().forEach(prof => {
    const opt = document.createElement('option');
    opt.value = opt.textContent = prof;
    sel.appendChild(opt);
  });
  // 保持当前选中的职业
  sel.value = currentProfession;
  sel.addEventListener('change', e => {
    currentProfession = e.target.value;
    clearProductSelection();
  });
}

// ====================  物料表格（包含即显示）  ====================
function initMaterialTable(highlightIds = new Set()) {
  const tbody = document.getElementById('materialTableBody');
  tbody.innerHTML = '';
  let used = 0, total = 0;
  const arr = [];
  RAW_MATERIALS.forEach(m => {
    if (m.source === '商店') return;
    if (currentProfession !== 'all') {
      const profs = m.professions.map(p => p.trim());
      if (!profs.includes(currentProfession)) return;
    }
    arr.push(m);
  });
  arr.sort((a, b) => highlightIds.has(b.id) - highlightIds.has(a.id) || getLocalizedName(a.name, currentRace).localeCompare(getLocalizedName(b.name, currentRace)));
  arr.forEach(m => {
    total++;
    const isUsed = highlightIds.has(m.id);
    if (isUsed) used++;
    const tr = document.createElement('tr');
    tr.className = isUsed ? 'highlighted' : '';
    // 使用本地化名称
    const localizedName = getLocalizedName(m.name, currentRace);
    tr.innerHTML = `
      <td>${localizedName}</td>
      <td>${m.source}</td>
      <td contenteditable="true" data-material-id="${m.id}">${m.price}</td>`;
    tbody.appendChild(tr);
  });
  document.getElementById('materialStats').textContent = `使用到的物料：${used} / ${total}`;
}

// ====================  产品搜索  ====================
const PRODUCT_LIST = (() => {
  const list = [];
  for (const [id, p] of Object.entries(PRODUCT_BOM)) {
    list.push({
      id, name: p.name, level: p.level, levelNum: p.levelNum || 0,
      profession: p.profession, calculation_coefficient: p.calculation_coefficient
    });
  }

  // 辅助函数：定义 入门(0) < 专业(1) 的排序权重
  const getLevelGroupRank = (level) => {
      if (level.startsWith('入门')) return 0;
      if (level.startsWith('专业')) return 1;
      return 2;
  };

  // 排序逻辑：职业 -> 等级前缀 (入门/专业) -> 数字 (levelNum)
  list.sort((a, b) => {
      // 1. 职业排序
      if (a.profession !== b.profession) {
          return a.profession.localeCompare(b.profession);
      }

      // 2. 等级前缀排序: 入门 (0) 在 专业 (1) 之前
      const rankA = getLevelGroupRank(a.level);
      const rankB = getLevelGroupRank(b.level);
      if (rankA !== rankB) {
          return rankA - rankB;
      }

      // 3. 数字排序: 在相同等级前缀内，按数字 (levelNum) 排序
      if (a.levelNum !== b.levelNum) {
          return a.levelNum - b.levelNum;
      }

      // 4. 最终以完整等级名称排序作为平局项
      return a.level.localeCompare(b.level);
  });

  return list;
})();

function initProductSearch() {
  const box = document.getElementById('productSearch');
  const drop = document.getElementById('productDropdown');
  box.addEventListener('click', e => {
    e.stopPropagation();
    box.value = '';
    currentProduct = null;
    showProductDropdown('');
  });
  // 搜索时，query应该能够匹配原始名称或本地化名称
  box.addEventListener('input', e => showProductDropdown(e.target.value.toLowerCase()));
  document.addEventListener('click', e => {
    if (!e.target.closest('.searchable-select')) drop.style.display = 'none';
  });
}
function showProductDropdown(query = '') {
  const drop = document.getElementById('productDropdown');
  drop.innerHTML = '';
  const filtered = PRODUCT_LIST.filter(p => {
    if (currentProfession !== 'all' && p.profession !== currentProfession) return false;
    if (!query) return true;
    
    // 允许匹配原始名称、本地化名称或ID
    const localizedName = getLocalizedName(p.name, currentRace).toLowerCase();
    const rawNameLower = p.name.toLowerCase();

    return localizedName.includes(query) || rawNameLower.includes(query) || p.id.toLowerCase().includes(query);
  });
  if (filtered.length === 0) {
    drop.innerHTML = '<div style="padding:16px;color:#86868b;text-align:center">无匹配产品</div>';
  } else {
    filtered.slice(0, 50).forEach(p => {
      const div = document.createElement('div');
      div.className = 'dropdown-item';
      // 使用本地化名称显示
      const localizedName = getLocalizedName(p.name, currentRace);
      div.innerHTML = `<div style="font-weight:600">[${p.level}] ${localizedName}</div>
                       <div style="font-size:12px;color:#86868b">编号: ${p.id} | 职业: ${p.profession}</div>`;
      div.onclick = () => {
        selectProduct(p);
        drop.style.display = 'none';
      };
      drop.appendChild(div);
    });
  }
  drop.style.display = 'block';
}
function selectProduct(p) {
  currentProduct = p;
  // 使用本地化名称显示在搜索框中
  document.getElementById('productSearch').value = getLocalizedName(p.name, currentRace);
  const highlightIds = getProductMaterialIds(p.id);
  initMaterialTable(highlightIds);
  generateBOMTree(p.id);
  calculateAndDisplayCost(p.id);
}
function clearProductSelection() {
  currentProduct = null;
  document.getElementById('productSearch').value = '';
  document.getElementById('treeContainer').innerHTML = '<div style="color:#86868b;text-align:center;padding:20px">请选择产品</div>';
  document.getElementById('totalCost').textContent = '0';
  document.getElementById('costDetailsBody').innerHTML = '请选择产品查看明细';
  initMaterialTable();
  toggleInstantSuccess(true);
}

// ====================  成本计算  ====================
function getProductMaterialIds(productId, visited = new Set()) {
  if (visited.has(productId)) return new Set();
  visited.add(productId);
  const p = PRODUCT_BOM[productId];
  if (!p) return new Set();
  const ids = new Set();
  p.materials.forEach(m => {
    if (m.id) ids.add(m.id);
    else if (m.ref) getProductMaterialIds(m.ref, new Set(visited)).forEach(id => ids.add(id));
  });
  return ids;
}
function calculateProductCost(productId, visited = new Set()) {
  if (visited.has(productId)) return { cost: 0, breakdown: {} };
  visited.add(productId);
  const p = PRODUCT_BOM[productId];
  if (!p) return { cost: 0, breakdown: {} };
  let total = 0, breakdown = {};
  const mult = (100 / currentSuccessRate) * p.calculation_coefficient;
  p.materials.forEach(m => {
    const qty = m.qty * mult;
    let cost = 0;
    if (m.ref) {
      const sub = calculateProductCost(m.ref, new Set(visited));
      cost = sub.cost * qty;
      Object.entries(sub.breakdown).forEach(([id, info]) => {
        if (!breakdown[id]) breakdown[id] = { name: info.name, qty: 0, cost: 0 };
        breakdown[id].qty += info.qty * qty;
        breakdown[id].cost += info.cost * qty;
      });
    } else if (m.id) {
      const mat = ALL_MATERIALS_MAP[m.id];
      if (!mat) return;
      cost = mat.price * qty;
      if (!breakdown[m.id]) breakdown[m.id] = { name: mat.name, qty: 0, cost: 0 };
      breakdown[m.id].qty += qty;
      breakdown[m.id].cost += cost;
    }
    total += cost;
  });
  return { cost: total, breakdown };
}
function calculateAndDisplayCost(productId) {
  // 同步价格
  document.querySelectorAll('#materialTableBody td[contenteditable=true]').forEach(cell => {
    const id = cell.dataset.materialId;
    const price = parseInt(cell.textContent) || 0;
    if (ALL_MATERIALS_MAP[id]) ALL_MATERIALS_MAP[id].price = price;
  });
  const res = calculateProductCost(productId);
  const final = res.cost;
  document.getElementById('totalCost').textContent = `${final.toFixed(0)}G`;
  const body = document.getElementById('costDetailsBody');
  body.innerHTML = '';
  const sorted = Object.entries(res.breakdown).sort((a, b) => b[1].cost - a[1].cost);
  sorted.forEach(([id, info]) => {
    const row = document.createElement('div');
    row.className = 'detail-row';
    // 使用本地化名称显示
    const localizedName = getLocalizedName(info.name, currentRace);
    row.innerHTML = `<span>${localizedName} (${Math.round(info.qty)}个)</span><span>${info.cost.toFixed(0)}G</span>`;
    body.appendChild(row);
  });
  const rateText = isInstantSuccess ? '一次性成功' : `${currentSuccessRate}% 成功率`;
  const totalRow = document.createElement('div');
  totalRow.className = 'detail-row';
  totalRow.innerHTML = `<span>总成本 (${rateText})</span><span>${final.toFixed(0)}G</span>`;
  body.appendChild(totalRow);
}

// ====================  BOM 树  ====================
function generateBOMTree(productId) {
  const container = document.getElementById('treeContainer');
  const p = PRODUCT_BOM[productId];
  if (!p) {
    container.innerHTML = '<div style="color:#86868b;text-align:center;padding:20px">请选择产品</div>';
    return;
  }
  // 注意：BOM面板已经有H3“产品结构BOM”，这里不再重复添加主产品H2/H3
  const html = createTreeNode(productId, p, 0);
  container.innerHTML = html;
  const rootBtn = container.querySelector('.toggle-btn');
  if (rootBtn) rootBtn.click();
}
function createTreeNode(pid, p, level, parentMult = 1) {
  const hasChildren = p.materials && p.materials.length;
  const margin = level * 12;
  const mult = parentMult * p.calculation_coefficient * (100 / currentSuccessRate);
  
  // 使用本地化产品名称
  const localizedProductName = getLocalizedName(p.name, currentRace);

  let html = `<div class="tree-node" style="margin-left:${margin}px;${level ? 'border-left:1px solid #e5e5ea' : ''}">
    <div class="node-header ${level === 0 ? 'tree-root' : ''}" onclick="toggleNode(this)">
      ${hasChildren ? '<button class="toggle-btn">+</button>' : '<div style="width:24px"></div>'}
      <div class="node-info" style="flex:1">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div><span class="node-name">${localizedProductName}</span>${p.calculation_coefficient !== 1 ? `<span class="coefficient-tag">系数: ${p.calculation_coefficient}x</span>` : ''}</div>
          ${level ? `<div class="material-info"><span class="qty-info">用量: ${Math.round(p.qty || 1)}个</span></div>` : ''}
        </div>
      </div>
    </div>`;
  if (hasChildren) {
    html += '<div class="children">';
    p.materials.forEach(m => {
      const qty = m.qty * mult;
      if (m.ref) {
        const child = PRODUCT_BOM[m.ref];
        if (child) {
          child.qty = qty;
          html += createTreeNode(m.ref, child, level + 1, mult);
        }
      } else if (m.id) {
        const mat = ALL_MATERIALS_MAP[m.id];
        if (mat) {
          const sub = mat.price * qty;
          // 使用本地化物料名称
          const localizedMaterialName = getLocalizedName(mat.name, currentRace);
          html += `<div class="tree-node" style="margin-left:${margin + 12}px">
            <div class="node-header">
              <div style="width:24px"></div>
              <div class="node-info" style="flex:1">
                <div style="display:flex;justify-content:space-between;align-items:center">
                  <span class="node-name">${localizedMaterialName}</span>
                  <div class="material-info">
                    <span class="qty-info">用量: ${Math.round(qty)}个</span>
                    <span class="price-info">单价: ${mat.price}</span>
                    <span class="subtotal-info">小计: ${sub.toFixed(0)}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>`;
        }
      }
    });
    html += '</div>';
  }
  html += '</div>';
  return html;
}
function toggleNode(header) {
  const children = header.nextElementSibling;
  if (children && children.classList.contains('children')) {
    children.classList.toggle('expanded');
    const btn = header.querySelector('.toggle-btn');
    btn.textContent = children.classList.contains('expanded') ? '−' : '+';
  }
}

// ====================  导出报告  ====================
function exportCostReport() {
  if (!currentProduct) { alert('请先选择一个产品'); return; }
  // 同步价格
  document.querySelectorAll('#materialTableBody td[contenteditable=true]').forEach(cell => {
    const id = cell.dataset.materialId;
    const price = parseInt(cell.textContent) || 0;
    if (ALL_MATERIALS_MAP[id]) ALL_MATERIALS_MAP[id].price = price;
  });
  const res = calculateProductCost(currentProduct.id);
  const final = res.cost;
  const date = new Date().toLocaleString('zh-CN');
  const p = PRODUCT_BOM[currentProduct.id];
  const rateText = isInstantSuccess ? '一次性成功' : `${currentSuccessRate}% 成功率`;
  const mult = (100 / currentSuccessRate).toFixed(2);
  
  // 使用本地化产品名称和版本信息
  const localizedProductName = getLocalizedName(currentProduct.name, currentRace);
  let txt = `永恒之塔2 制作成本报告 (${currentRace === 'T' ? '天族' : '魔族'}版本)\n生成时间: ${date}\n产品名称: ${localizedProductName}\n制作等级: ${currentProduct.level}\n制作职业: ${p.profession}\n计算系数: ${p.calculation_coefficient}x\n成功率设定: ${rateText}\n成功率系数: ${mult}x\n────────────────────────\n总成本: ${final.toFixed(0)}G\n────────────────────────\n成本构成明细:\n`;
  
  const sorted = Object.entries(res.breakdown).sort((a, b) => b[1].cost - a[1].cost);
  sorted.forEach(([id, info]) => {
    const pct = (info.cost / final * 100).toFixed(1);
    // 使用本地化物料名称
    const localizedMaterialName = getLocalizedName(info.name, currentRace);
    txt += `${localizedMaterialName.padEnd(22)} x${Math.round(info.qty).toString().padStart(7)}  ${info.cost.toFixed(0).padStart(12)}G  (${pct}%)\n`;
  });
  txt += `\n💡 提示：成本基于当前交易行物价计算，成功率系数已应用。\n`;
  const blob = new Blob([txt], { type: 'text/plain;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${p.profession}_${localizedProductName}_系数${p.calculation_coefficient}_${rateText}_${Date.now()}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

// ====================  事件监听  ====================
document.addEventListener('keydown', e => {
  if (e.target.matches('td[contenteditable=true]') && !['Backspace','Delete','ArrowLeft','ArrowRight','Tab','Home','End'].includes(e.key) && !e.key.match(/[0-9]/)) {
    e.preventDefault();
  }
});
document.addEventListener('input', e => {
  if (e.target.matches('td[contenteditable=true]')) {
    const cur = e.target.textContent;
    const cleaned = cur.replace(/[^0-9]/g, '');
    if (cur !== cleaned) e.target.textContent = cleaned;
    const id = e.target.dataset.materialId;
    const price = parseInt(cleaned) || 0;
    if (ALL_MATERIALS_MAP[id]) {
      ALL_MATERIALS_MAP[id].price = price;
      if (currentProduct) {
        calculateAndDisplayCost(currentProduct.id);
        generateBOMTree(currentProduct.id);
      }
    }
  }
});
document.addEventListener('focusout', e => {
  if (e.target.matches('td[contenteditable=true]') && e.target.textContent === '') {
    e.target.textContent = '0';
    const id = e.target.dataset.materialId;
    if (ALL_MATERIALS_MAP[id]) {
      ALL_MATERIALS_MAP[id].price = 0;
      if (currentProduct) {
        calculateAndDisplayCost(currentProduct.id);
        generateBOMTree(currentProduct.id);
      }
    }
  }
});

// ====================  初始化  ====================
document.addEventListener('DOMContentLoaded', () => {
  const raceSelector = document.getElementById('race-selector');
  // 绑定种族选择事件，并在切换时更新所有相关组件
  if (raceSelector) {
    raceSelector.addEventListener('change', (e) => {
      currentRace = e.target.value;
      // 重新初始化并更新所有依赖种族名称的组件
      initProfessionFilter();
      initMaterialTable();
      initProductSearch();
      // 如果有当前选中产品，重新计算并渲染BOM
      if (currentProduct) {
          // 更新产品搜索框的显示名称
          document.getElementById('productSearch').value = getLocalizedName(currentProduct.name, currentRace);
          calculateAndDisplayCost(currentProduct.id);
          generateBOMTree(currentProduct.id);
      }
    });
  }

  // 首次加载初始化
  initProfessionFilter();
  initMaterialTable();
  initProductSearch();

  // 成功率
  const chk = document.getElementById('instantSuccessCheckbox');
  const inp = document.getElementById('successRateInput');
  chk.addEventListener('change', e => toggleInstantSuccess(e.target.checked));
  inp.addEventListener('input', e => {
    let v = parseInt(e.target.value);
    if (isNaN(v)) v = 25;
    if (v < 1) v = 1;
    if (v > 100) v = 100;
    e.target.value = v;
    updateSuccessRate(v);
  });
  inp.addEventListener('blur', e => {
    if (e.target.value === '') {
      e.target.value = '25';
      updateSuccessRate(25);
    }
  });
  toggleInstantSuccess(true);
  console.log('🛠️ 永恒之塔2 制作计算器已加载完成');
});
</script>
</body>
</html>"""

# --------------------  生成 HTML  --------------------
def generate_html(material_items, recipe_data):
    print("\n" + "="*60)
    print("[步骤3] 生成 HTML")
    print("="*60)
    
    # 检查数据有效性
    if not material_items:
        print("[✗] 物料数据为空，无法生成HTML")
        input("\n按 Enter 退出...")
        sys.exit(1)
    if not recipe_data:
        print("[✗] 配方数据为空，无法生成HTML")
        input("\n按 Enter 退出...")
        sys.exit(1)
    
    html = HTML_TEMPLATE.replace('/*AUTO_GENERATED_MATERIALS*/', json.dumps(material_items, ensure_ascii=False, indent=2)[1:-1])
    html = html.replace('/*AUTO_GENERATED_RECIPES*/', json.dumps(recipe_data, ensure_ascii=False, indent=2)[1:-1])
    out = Path(CFG["HTML_OUT"])
    
    try:
        out.write_text(html, encoding='utf-8')
        print(f"[✓] HTML 已生成：{out.resolve()}")
        print(f"[📊] 文件大小: {len(html)/1024:.1f} KB")
    except Exception as e:
        print(f"[✗] 写入文件失败: {e}")
        input("\n按 Enter 退出...")
        sys.exit(1)

# --------------------  主流程  --------------------
def main():
    print("\n" + "="*60)
    print("  AION 综合转换工具 v5.5  终极修复版")
    print("="*60)
    print("所需文件：")
    print(f"  - {CFG['MATERIAL_CSV']}  （原料名称,制作职业,来源,单价）")
    print(f"  - {CFG['BOM_CSV']}       （制作职业,名称,需求等级,计算系数,材料1,数量1,...,材料9,数量9）")
    print("输出文件：")
    print(f"  - {CFG['HTML_OUT']}")
    print("="*60)
    
    try:
        material_items = convert_material()
        recipe_data, _ = convert_bom({m['name']: m['id'] for m in material_items})
        generate_html(material_items, recipe_data)
        
        print("\n" + "="*60)
        print("[🎉] 全部完成！")
        print("="*60)
        print(f"\n📊 最终数据汇总:")
        print(f"  ├─ 基础材料: {len(material_items)} 种")
        print(f"  ├─ 产品配方: {len(recipe_data)} 条")
        print(f"  ├─ 制作职业: {len(set(p['profession'] for p in recipe_data.values()))} 个")
        print(f"  └─ 生成文件: {Path(CFG['HTML_OUT']).resolve()}")
        print("\n🎯 下一步: 双击打开 index_generated.html 开始使用")
        print("="*60)
        
    except Exception as e:
        print(f"\n[✗] 程序异常终止: {e}")
        traceback.print_exc()
        input("\n按 Enter 退出...")
    
    input("\n按 Enter 退出程序...")

if __name__ == '__main__':
    main()