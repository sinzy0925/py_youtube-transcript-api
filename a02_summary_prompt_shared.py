#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
a02 — プロンプト定義（直接実行しない）
    要約の指示文を a03 から import する。パイプライン順: a01 → a02(import) → a03 → a04。
    Groq / Gemini の要約プロンプトを同一に保つ（detailed / financial 等の本文はここが唯一のソース）。
"""

from __future__ import annotations

import os

# パイプライン未指定時・mode 空時の既定
DEFAULT_PROMPT_MODE = "financial"

# 旧 Groq の system と同等の拘束を、両モデルに同じ user 冒頭で渡す
_ROLE_AND_OUTPUT = (
    "【役割】あなたは動画の文字起こしを要約するアシスタントです。\n"
    "【出力】指定どおり日本語のプレーンテキストのみ。"
    "前置き・挨拶・コードフェンス（```）は使わない。\n"
    "【事実表現】実在の地名・国名・紛争・歴史・企業名など、公的に報道・記録されている事柄が出る箇所では、\n"
    "文字起こしが比喩・仮定・シナリオ説明（「もし」系）なのか、時事解説なのかを区別する。\n"
    "知られている実事を、根拠なく『架空』『作り話』扱いする表現は避ける。不確かな点は不確かと書く。\n"
)

_FINANCIAL_BODY = (
    "以下の文字起こしを、投資・年金・税金・介護・補助金・資産形成など"
    "金融・福祉・制度解説向けに詳細要約してください。\n\n"
    "【必須セクション（見出し付き）】\n"
    "1. 一言サマリー（誰向け・テーマ）\n"
    "2. 対象者・前提条件（年齢、所得、世帯、雇用形態 等）\n"
    "3. 制度・商品・施策名と要点\n"
    "4. 数字一覧（金額・率・上限・期限）※文字起こしにあるもののみ。無い数字は捏造しない\n"
    "5. メリット / デメリット / リスク\n"
    "6. 視聴者が取れるアクション（手順・時期）\n"
    "7. 注意・免責（個別事情で変わる点、動画主張≠公式見解）\n"
    "8. 公式確認先（下記参照リストから該当のみ列挙。無ければ「該当官公庁サイトで要確認」）\n\n"
    "【ルール】\n"
    "・YouTube の断定表現は「動画内では〜との説明」と出所を区別する\n"
    "・推測は「推測:」と明示\n"
    "・補助金・非課税・住民税は詐欺・自治体差の注意を1文入れる\n"
    "・文字起こしにない制度改定年・税率・上限を書かない\n\n"
    "【禁止】文字起こしにない事実の捏造、過度な一般化、「確実に儲かる」等の誇張をそのまま断定。"
)


def resolve_prompt_mode(mode: str) -> str:
    """CLI / env 未指定時は SUMMARY_PROMPT_MODE → DEFAULT_PROMPT_MODE。"""
    m = (mode or os.getenv("SUMMARY_PROMPT_MODE") or DEFAULT_PROMPT_MODE).strip().lower()
    return m or DEFAULT_PROMPT_MODE


def build_prompt(
    mode: str,
    custom_prompt: str,
    video_title: str,
    video_url: str,
    *,
    reference_block: str = "",
) -> str:
    """
    文字起こし本文の直前までのプロンプト（--- 文字起こし本文 --- は呼び出し側で付与）。
    mode: brief | detailed | financial | minutes | custom
    """
    mode = resolve_prompt_mode(mode)
    head = (
        _ROLE_AND_OUTPUT
        + f"対象動画タイトル: {video_title}\n"
        + f"対象動画URL: {video_url}\n"
        + "出力言語: 日本語\n"
        + "出力形式: プレーンテキスト\n"
    )
    if mode == "minutes":
        body = (
            "以下の文字起こしを議事録形式に整理してください。\n"
            "見出し: 概要 / 決定事項 / ToDo / 未決事項 / 補足\n"
            "箇条書き中心で簡潔に。"
        )
    elif mode == "financial":
        body = _FINANCIAL_BODY
    elif mode == "detailed":
        body = (
            "以下の文字起こしを詳細要約してください。\n\n"
            "【構成の目安】\n"
            "・冒頭に全体の要約を2〜4文で書く。\n"
            "・見出し付きで章立てし、重要ポイント・背景・結論・視聴者向けの注意点・"
            "取りうるアクションを整理する。\n"
            "・金額・年・要件・制度名・固有名詞は、可能な限り文字起こしの表現に合わせて残す。\n"
            "・推測が必要な箇所は「推測:」と明示し、断定しない。\n"
            "・国際情勢・紛争・企業等の固有名を扱う場合、文字起こしの趣旨（時事解説なのか比喩なのか）に沿って要約し、\n"
            "実在の公的に知られた出来事を『創作』のように書かない。\n\n"
            "【禁止】文字起こしにない事実の捏造、過度な一般化。"
        )
    elif mode == "custom":
        body = custom_prompt.strip() or "以下の文字起こしを要約してください。"
    else:
        body = "以下の文字起こしを簡易要約してください。要点を箇条書きで短くまとめてください。"
    ref = (reference_block or "").strip()
    if ref:
        body = f"{body}\n\n{ref}"
    return f"{head}\n{body}"


def build_truth_assessment_prompt_for_summary(
    video_title: str,
    video_url: str,
    *,
    reference_block: str = "",
) -> str:
    """
    要約本文に対する真実度（検索+プロンプトJSON 用）。
    文字起こし全文は渡さない。Google 検索で要約内の主張を公開情報と照合可能。
    """
    ref = (reference_block or "").strip()
    ref_section = f"\n{ref}\n" if ref else ""
    return (
        "【役割】以下の「要約文」について、信頼性の目安（0〜100）を JSON で返す。"
        "評価対象は要約文のみ（文字起こし全文は与えない）。\n"
        "【観点】\n"
        "・数字・制度名・条件の記載が要約内で一貫しているか\n"
        "・断定・誇張の追加がないか（「動画内説明」「推測」の区別が適切か）\n"
        "・注意・免責・公式確認先の記載があるか（制度・税金・補助金系）\n"
        "・利用可能なら Google 検索で要約内の主要な固有名・制度・数値の桁を公開情報と照合\n"
        "【出力形式】Google 検索ツールは利用してよい。"
        "応答本文は **有効な JSON オブジェクト 1 個だけ**。"
        "前後に説明・マークダウン・コードフェンスを付けない。\n"
        + ref_section
        + f"対象動画タイトル: {video_title}\n"
        + f"対象動画URL: {video_url}\n"
        "以下の区切りの後が「要約文」です。\n"
        "score_percent: 0〜100 の整数\n"
        "reason: 日本語3〜7文。検索で確認した点があれば簡潔に。\n"
        '厳密な形式: {"score_percent": <整数>, "reason": "<文字列>"}\n'
    )


def build_truth_assessment_prompt(
    video_title: str,
    video_url: str,
    *,
    json_via_api_schema: bool = True,
) -> str:
    """
    文字起こし全文用（レガシー／search_google.py 等）。要約パイプラインでは for_summary を使用。
    """
    if json_via_api_schema:
        api_form = (
            "【API 形式】応答は **JSON オブジェクトそのもの**のみ。マークダウン・太字・箇条書き・前後の説明は禁止\n"
            "（**システムがスキーマで厳制する**。reason 内もプレーンテキスト、*や#は使わない）。\n"
        )
    else:
        api_form = (
            "【出力形式（重要）】**Google 検索ツールは利用してよい**が、この呼び出しでは **API 側は JSON を強制しない**。\n"
            "したがって **応答本文は有効な JSON オブジェクト 1 個だけ** とし、"
            "**その前後に説明文・挨拶・マークダウン・コードフェンス（```）・注釈を一切付けない**。\n"
            "プログラムが `json.loads` で解析する。reason はプレーンテキスト（* や # は使わない）。\n"
        )
    return (
        "【役割】与えられた文字起こし（要約前の全文）について、"
        "後段の要約の土台としての『妥当性・信頼性の目安』を採点する。あくまで目安（完璧な事実審判ではない）。\n"
        "【特に重視：実在事柄の誤認の防止】\n"
        "国名・国際紛争名・年号・大企業名・公人名など、**実在の時事・歴史的事柄**が出る箇所では、\n"
        "次を必ず意識する：\n"
        "1) 文字起こしの語りが「時事解説・学説的説明」なのか、「仮定・比喩・想定」なのかを区別する。\n"
        "2) **公に報道・百科・公的機関等で裏取り可能な事柄**を、安易に「架空の設定」「作り話」扱いしない。\n"
        "3) 利用可能なら、固有名の主要なものについて **公開情報（検索等）** を参照し、\n"
        "   国名の存在・紛争の実在性・大まかな時期感など、一般に定着している知識と食い違っていないかを確認してから採点する。\n"
        "4) 出典の明記が少なく、一次情報（当事者の直接の言明）やデータが無い点は、信頼度の減点要因にしてよいが、\n"
        "   『実在の出来事の説明』を『小説的虚構』と取り違えて大きく点を下げる誤りは避ける。\n"
        + api_form
        + f"対象動画タイトル: {video_title}\n"
        + f"対象動画URL: {video_url}\n"
        "以下の区切りの後に続くのは「文字起こし全文（要約前）」です。\n"
        '厳密な形式: {"score_percent": <整数>, "reason": "<文字列>"}\n'
    )


def build_truth_assessment_prompt_relaxed(video_title: str, video_url: str) -> str:
    """検索・自由形式／自由形式用（レガシー）。"""
    return (
        "【役割】文字起こし（要約前全文）の信頼性目安を 0〜100 で付け、根拠を述べる。\n"
        "可能なら **本文中に 1 か所**、次の形式の JSON のみを含める（コードフェンスは使わない）：\n"
        '{"score_percent": <0〜100の整数>, "reason": "<日本語で3〜7文>"}\n'
        f"対象: {video_title} / {video_url}\n"
    )
