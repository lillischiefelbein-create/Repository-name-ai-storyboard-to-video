"""影视前期视觉资产管理 Skill 的离线状态处理模块。

没有账号连接、外部素材检索、图像生成或飞书写入操作。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any


class 流程错误(ValueError):
    """操作不满足资产审批规则。"""


def _解析时间(时间: str) -> datetime:
    try:
        结果 = datetime.fromisoformat(时间)
    except (TypeError, ValueError) as 错误:
        raise 流程错误("时间必须使用 ISO 格式并包含时区") from 错误
    if 结果.tzinfo is None or 结果.utcoffset() is None:
        raise 流程错误("时间必须包含时区")
    return 结果


def _检查资产(资产: dict[str, Any]) -> None:
    if not 资产.get("资产编号"):
        raise 流程错误("缺少资产编号")
    if 资产.get("当前版本") == "终稿" and 资产.get("状态") != "已终稿":
        raise 流程错误("终稿版本必须处于已终稿状态")


def 审核参考(资产: dict[str, Any], 参考编号: str, 决定: str, 否决原因: str = "") -> dict[str, Any]:
    """只有明确按钮值才能产生审批结果。"""
    _检查资产(资产)
    if 资产.get("状态") == "已终稿":
        raise 流程错误("终稿已锁定")
    if 决定 not in ("通过", "否决"):
        raise 流程错误("审批结果只能是通过或否决")
    if 决定 == "否决" and not 否决原因.strip():
        raise 流程错误("否决必须有原因")
    结果 = deepcopy(资产)
    参考 = next((项 for 项 in 结果.get("参考素材", []) if 项.get("参考编号") == 参考编号), None)
    if 参考 is None:
        raise 流程错误("参考不存在")
    参考["审批"] = 决定
    参考["否决原因"] = 否决原因 if 决定 == "否决" else ""
    if 结果.get("当前版本") == "待生成":
        已用 = []
        for 项 in 结果.get("参考素材", []):
            if 项.get("审批") == "通过":
                for 元素 in 项.get("提取元素", []):
                    if 元素 not in 已用:
                        已用.append(元素)
        结果["当前采用元素"] = 已用
    结果.setdefault("参考审核历史", []).append(
        {"参考编号": 参考编号, "决定": 决定, "否决原因": 否决原因})
    结果["状态"] = "参考已确认" if 参考覆盖完整(结果) else "参考审核中"
    return 结果


def 参考覆盖完整(资产: dict[str, Any]) -> bool:
    必需 = set(资产.get("必需参考部位", []))
    通过部位: set[str] = set()
    for 参考 in 资产.get("参考素材", []):
        if 参考.get("审批") == "通过":
            通过部位.update(参考.get("应用部位", []))
    return bool(必需) and 必需.issubset(通过部位)


def 检查是否可生成(资产: dict[str, Any]) -> bool:
    必需 = set(资产.get("必需参考部位", []))
    return (
        资产.get("状态") != "已终稿"
        and 资产.get("允许生成") is True
        and 参考覆盖完整(资产)
        and not any(
            项.get("审批") == "待审核"
            and set(项.get("应用部位", [])) & 必需
            for 项 in 资产.get("参考素材", [])
        )
    )


def 开始反馈(资产: dict[str, Any], 截止时间: str, 按钮: str) -> dict[str, Any]:
    _检查资产(资产)
    if 按钮 != "需要修改":
        raise 流程错误("必须点击需要修改")
    if 资产.get("状态") == "已终稿":
        raise 流程错误("已终稿")
    if not 资产.get("当前资产图") or 资产.get("当前版本") == "待生成":
        raise 流程错误("尚无可修改的图片")
    _解析时间(截止时间)
    结果 = deepcopy(资产)
    结果["反馈截止时间"] = 截止时间
    结果["状态"] = "反馈收集中"
    结果["反馈"] = []
    return 结果


def 添加反馈(资产: dict[str, Any], 提交人: str, 意见: str, 提交时间: str,
        参考编号: str = "") -> dict[str, Any]:
    if 资产.get("状态") != "反馈收集中":
        raise 流程错误("不在反馈期")
    if not 意见.strip():
        raise 流程错误("意见不能为空")
    if _解析时间(提交时间) > _解析时间(资产["反馈截止时间"]):
        raise 流程错误("已超过截止时间")
    结果 = deepcopy(资产)
    结果["反馈"].append(
        {"提交人": 提交人, "意见": 意见, "提交时间": 提交时间, "参考编号": 参考编号})
    return 结果


def 截止归纳(资产: dict[str, Any], 当前时间: str) -> dict[str, Any]:
    """精确文本去重和生成快照，后续可接语义归纳模型。"""
    if 资产.get("状态") != "反馈收集中":
        raise 流程错误("不在反馈期")
    if _解析时间(当前时间) < _解析时间(资产["反馈截止时间"]):
        raise 流程错误("尚未截止")
    结果 = deepcopy(资产)
    合并: dict[str, list[str]] = {}
    for 项 in 结果.get("反馈", []):
        规范 = " ".join(项["意见"].strip().split())
        合并.setdefault(规范, []).append(项["提交人"])
    结果["本轮反馈归纳"] = [
        {"问题": 内容, "反馈人数": len(作者), "反馈人": 作者}
        for 内容, 作者 in 合并.items()
    ]
    结果["反馈快照"] = deepcopy(结果["反馈"])
    结果["状态"] = "待制定精修指令"
    return 结果


def 继承并修订元素(上一版: list[str], *, 保留: list[str] | None = None,
            删除: list[str] | None = None,
            替换: dict[str, str] | None = None,
            新增: list[str] | None = None,
            强化: dict[str, str] | None = None) -> dict[str, Any]:
    """所有变化均基于上一个版本，保留修改的可追溯记录。"""
    原始 = list(dict.fromkeys(上一版))
    保留 = 原始 if 保留 is None else 保留
    删除 = 删除 or []
    替换 = 替换 or {}
    新增 = 新增 or []
    强化 = 强化 or {}
    if any(项 not in 原始 for 项 in 删除 + list(替换) + list(强化)):
        raise 流程错误("修改目标必须存在于上一版")
    if any(项 not in 原始 for 项 in 保留):
        raise 流程错误("保留项必须来自上一版")
    新版 = []
    for 项 in 原始:
        if 项 in 删除:
            continue
        值 = 替换.get(项, 强化.get(项, 项))
        if 值 not in 新版:
            新版.append(值)
    for 项 in 新增:
        if 项 not in 新版:
            新版.append(项)
    return {
        "继承基线": 原始,
        "保留": [项 for 项 in 原始 if 项 not in 删除 and 项 not in 替换 and 项 not in 强化],
        "删除": 删除, "替换": 替换, "强化": 强化, "新增": 新增,
        "当前采用元素": 新版,
    }


def 发布图片版本(资产: dict[str, Any], 图片链接: str, *,
            版本修订: dict[str, Any] | None = None) -> dict[str, Any]:
    """图片必须先经外部服务成功保存，才能更新版本；本函数不实际生成图片。"""
    _检查资产(资产)
    if not 图片链接.strip():
        raise 流程错误("图片链接或附件标识不能为空")
    if not 检查是否可生成(资产):
        raise 流程错误("必须先完成参考审核并允许生成")
    旧版 = 资产.get("当前版本", "待生成")
    if 旧版 == "待生成":
        新版 = "初版"
    elif 旧版 == "初版":
        新版 = "1修"
    elif 旧版.endswith("修") and 旧版[:-1].isdigit():
        新版 = f"{int(旧版[:-1]) + 1}修"
    else:
        raise 流程错误("不支持该版本继续生成")
    结果 = deepcopy(资产)
    if 旧版 != "待生成":
        if 资产.get("状态") != "待制定精修指令":
            raise 流程错误("修改前需要完成反馈截止归纳")
        结果.setdefault("历史版本", []).append({
            "版本": 旧版, "图片": 资产.get("当前资产图"),
            "采用元素": deepcopy(资产.get("当前采用元素", [])),
            "反馈归纳": deepcopy(资产.get("本轮反馈归纳", [])),
            "参考素材": deepcopy(资产.get("参考素材", []))
        })
        if 版本修订 is not None:
            结果.setdefault("元素变更历史", []).append(deepcopy(版本修订))
            结果["当前采用元素"] = deepcopy(版本修订["当前采用元素"])
    结果["当前版本"] = 新版
    结果["当前资产图"] = 图片链接
    结果["状态"] = "待审核"
    return 结果


def 标记无需修改(资产: dict[str, Any], 按钮: str) -> dict[str, Any]:
    if 按钮 != "无需修改":
        raise 流程错误("必须点击无需修改")
    if 资产.get("状态") != "待审核" or not 资产.get("当前资产图"):
        raise 流程错误("当前资产不能提交终稿确认")
    结果 = deepcopy(资产)
    结果["状态"] = "待终稿确认"
    return 结果


def 终稿确认(资产: dict[str, Any], 按钮: str) -> dict[str, Any]:
    if 按钮 != "确认终稿":
        raise 流程错误("必须明确点击确认终稿")
    if 资产.get("状态") != "待终稿确认" or not 资产.get("当前资产图"):
        raise 流程错误("尚未满足终稿条件")
    结果 = deepcopy(资产)
    结果["已确认版本"] = 结果["当前版本"]
    结果["当前版本"] = "终稿"
    结果["状态"] = "已终稿"
    结果["最终图"] = 结果["当前资产图"]
    return 结果


def 同步顺场图(资产列表: list[dict[str, Any]],
          顺场记录: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """返回可用于飞书同步的当前资产图片和缺失清单。"""
    资产索引 = {项["资产编号"]: 项 for 项 in 资产列表}
    输出 = []
    for 场次 in 顺场记录:
        记录 = deepcopy(场次)
        记录["自动插入资产"] = []
        记录["缺失资产"] = []
        for 编号 in 场次.get("资产编号列表", []):
            资产 = 资产索引.get(编号)
            if not 资产:
                记录["缺失资产"].append(编号)
                continue
            记录["自动插入资产"].append({
                "资产编号": 编号,
                "类别": 资产.get("大类"),
                "当前版本": 资产.get("当前版本"),
                "当前图片": 资产.get("当前资产图", ""),
                "状态": 资产.get("状态", "")
            })
            if not 资产.get("当前资产图"):
                记录["缺失资产"].append(编号)
        输出.append(记录)
    return 输出
