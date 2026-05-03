import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from datetime import datetime
from pathlib import Path

REQUIRED_COLUMNS = [
    "Дата",
    "Тип договора",
    "Дней на согласование",
    "Сумма риска (руб)",
    "Оценка бизнеса",
]

COL_PREP_METHOD = "Способ подготовки"
COL_LAWYER = "Ответственный юрист"


def _format_rub(value: float) -> str:
    try:
        v = float(value)
    except Exception:
        return "—"
    s = f"{v:,.0f}".replace(",", " ")
    return f"{s} ₽"


def _validate_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def render_sidebar_header() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div style="font-size: 2.1rem; line-height: 1; margin: 0.1rem 0 0.6rem 0;">⚖️</div>
            <div style="font-weight: 700; font-size: 1.05rem; line-height: 1.25;">
              Правовой департамент: Система целеполагания с использованием бизнес-метрик
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.divider()


def render_contract_type_filter(df: pd.DataFrame) -> list[str]:
    all_types = sorted([t for t in df["Тип договора"].dropna().unique().tolist() if t])
    st.sidebar.header("Фильтр")
    return st.sidebar.multiselect(
        "Тип договора",
        options=all_types,
        default=all_types,
        key="filter_contract_types",
    )


def compute_automation_pct(df: pd.DataFrame) -> float | None:
    if COL_PREP_METHOD not in df.columns:
        return None

    s = df[COL_PREP_METHOD].astype(str).str.strip()
    s_norm = s.str.casefold()
    denom = int(s_norm.notna().sum())
    if denom == 0:
        return None

    auto = s_norm.isin(["конструктор", "шаблон"])
    return float(auto.sum() / denom)


def lawyer_workload_latest_month(df: pd.DataFrame) -> tuple[pd.DataFrame | None, pd.Timestamp | None]:
    if COL_LAWYER not in df.columns:
        return None, None

    tmp = df.copy()
    if "Дата" not in tmp.columns:
        return None, None

    tmp["Дата"] = pd.to_datetime(tmp["Дата"], errors="coerce")
    tmp = tmp[tmp["Дата"].notna()].copy()
    if tmp.empty:
        return None, None

    latest = pd.Timestamp(tmp["Дата"].max()).normalize()
    month_mask = (tmp["Дата"].dt.year == latest.year) & (tmp["Дата"].dt.month == latest.month)
    m = tmp.loc[month_mask].copy()
    if m.empty:
        return None, latest

    m[COL_LAWYER] = m[COL_LAWYER].astype(str).str.strip()
    m = m[m[COL_LAWYER].notna() & (m[COL_LAWYER] != "")].copy()
    if m.empty:
        return None, latest

    counts = (
        m.groupby(COL_LAWYER, dropna=False)
        .size()
        .rename("Документов")
        .reset_index()
        .sort_values("Документов", ascending=True)
    )
    counts["overload"] = counts["Документов"] > 15
    return counts, latest


def workload_plotly_figure(counts: pd.DataFrame) -> go.Figure:
    lawyers = counts[COL_LAWYER].astype(str)
    docs = counts["Документов"].astype(int)
    overload = counts["overload"].astype(bool)

    colors = ["#ef4444" if o else "#2563eb" for o in overload.tolist()]

    fig = go.Figure(
        data=[
            go.Bar(
                x=docs,
                y=lawyers,
                orientation="h",
                marker_color=colors,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Документов: <b>%{x}</b><extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Документов",
        yaxis_title="",
        showlegend=False,
        height=max(240, 28 * counts.shape[0]),
    )
    return fig


@st.cache_data(show_spinner=False)
def load_contracts_xlsx(path: str = "data.xlsx") -> pd.DataFrame:
    return pd.read_excel(path)


@st.cache_data(show_spinner=False)
def load_feedback_csv(path: str = "feedback.csv") -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def load_ip_xlsx(path: str = "data.xlsx", sheet_name: str = "IP_Data") -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet_name)


def ip_foreign_countries_figure(country_counts: pd.Series) -> go.Figure:
    countries = country_counts.index.astype(str).tolist()
    values = country_counts.values.tolist()
    fig = go.Figure(
        data=[
            go.Bar(
                x=values,
                y=countries,
                orientation="h",
                marker_color="#2563eb",
                hovertemplate="<b>%{y}</b><br>Знаков: <b>%{x}</b><extra></extra>",
            )
        ]
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis_title="Количество ТЗ",
        yaxis_title="",
        showlegend=False,
        height=max(260, 26 * max(1, len(countries))),
    )
    return fig


def save_feedback(*, lawyer: str, score: int, comment: str) -> None:
    feedback_path = Path("feedback.csv")
    row = pd.DataFrame(
        [
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "lawyer": lawyer,
                "score": int(score),
                "comment": comment,
            }
        ]
    )
    row.to_csv(
        feedback_path,
        index=False,
        mode="a",
        header=not feedback_path.exists(),
        encoding="utf-8",
    )


def _progress_bar_html(pct: float) -> str:
    p = float(pct)
    p = max(0.0, min(1.0, p))
    if p < 0.5:
        color = "#ef4444"
    elif p < 0.8:
        color = "#f59e0b"
    else:
        color = "#22c55e"

    width = int(round(p * 100))
    return f"""
      <div class="okr-bar-track">
        <div class="okr-bar-fill" style="width:{width}%; background:{color};"></div>
      </div>
    """


def main() -> None:
    st.set_page_config(
        page_title="LegalApp · Дашборд",
        page_icon="⚖️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    render_sidebar_header()

    st.markdown(
        """
        <style>
          :root { --card-bg: rgba(255,255,255,0.72); --card-br: 16px; }
          .block-container { padding-top: 1.3rem; }
          div[data-testid="stMetric"] {
            background: var(--card-bg);
            border: 1px solid rgba(0,0,0,0.06);
            padding: 14px 16px;
            border-radius: var(--card-br);
            box-shadow: 0 8px 22px rgba(0,0,0,0.06);
          }
          div[data-testid="stMetricLabel"] p { font-size: 0.95rem; opacity: 0.85; }
          div[data-testid="stMetricValue"] { font-size: 1.9rem; }
          .pill {
            display: inline-block;
            padding: 0.15rem 0.55rem;
            border-radius: 999px;
            font-size: 0.85rem;
            font-weight: 600;
            border: 1px solid rgba(0,0,0,0.08);
          }
          .pill-work { background: rgba(59, 130, 246, 0.12); color: rgb(30, 64, 175); }
          .pill-done { background: rgba(34, 197, 94, 0.14); color: rgb(20, 83, 45); }
          .pill-crit { background: rgba(239, 68, 68, 0.14); color: rgb(153, 27, 27); }
          .action-card {
            background: rgba(255,255,255,0.7);
            border: 1px solid rgba(0,0,0,0.06);
            border-radius: 16px;
            padding: 14px 16px;
            box-shadow: 0 8px 22px rgba(0,0,0,0.06);
          }
          .okr-bar-track {
            width: 100%;
            height: 10px;
            border-radius: 999px;
            background: rgba(0,0,0,0.08);
            overflow: hidden;
          }
          .okr-bar-fill {
            height: 100%;
            border-radius: 999px;
            transition: width 200ms ease;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("⚖️ LegalApp")
    st.caption("Аналитика договоров и сбор отзывов о сервисе.")

    try:
        feedback_df = load_feedback_csv("feedback.csv")
    except FileNotFoundError:
        feedback_df = pd.DataFrame(columns=["timestamp", "lawyer", "score", "comment"])
    except Exception:
        feedback_df = pd.DataFrame(columns=["timestamp", "lawyer", "score", "comment"])

    if "score" in feedback_df.columns:
        feedback_df["score"] = pd.to_numeric(feedback_df["score"], errors="coerce")

    avg_nps_from_feedback = (
        feedback_df["score"].mean(skipna=True) if "score" in feedback_df.columns else float("nan")
    )

    tab_analytics, tab_feedback, tab_goals, tab_ip = st.tabs(
        ["Аналитика бизнес-метрик", "Оценка сервиса", "Стратегические цели", "IP"]
    )

    with tab_analytics:
        try:
            df = load_contracts_xlsx("data.xlsx")
        except FileNotFoundError:
            st.info("Создайте data.xlsx")
            st.stop()
        except Exception as e:
            st.error(f"Не удалось прочитать `data.xlsx`: {e}")
            st.stop()

        missing = _validate_columns(df)
        if missing:
            st.error("В `data.xlsx` не хватает колонок: " + ", ".join(f"‘{c}’" for c in missing))
            st.stop()

        df = df.copy()
        df["Дата"] = pd.to_datetime(df["Дата"], errors="coerce")
        df["Тип договора"] = df["Тип договора"].astype(str).str.strip()
        df["Дней на согласование"] = pd.to_numeric(df["Дней на согласование"], errors="coerce")
        df["Сумма риска (руб)"] = pd.to_numeric(df["Сумма риска (руб)"], errors="coerce")
        df["Оценка бизнеса"] = pd.to_numeric(df["Оценка бизнеса"], errors="coerce")
        if COL_PREP_METHOD in df.columns:
            df[COL_PREP_METHOD] = df[COL_PREP_METHOD].astype(str).str.strip()
        if COL_LAWYER in df.columns:
            df[COL_LAWYER] = df[COL_LAWYER].astype(str).str.strip()

        selected_types = render_contract_type_filter(df)
        if selected_types:
            df_f = df[df["Тип договора"].isin(selected_types)].copy()
        else:
            df_f = df.iloc[0:0].copy()

        avg_days = df_f["Дней на согласование"].mean(skipna=True)
        total_risk = df_f["Сумма риска (руб)"].sum(skipna=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Среднее время согласования", "—" if pd.isna(avg_days) else f"{avg_days:.1f} дн.")
        c2.metric("Предотвращённые риски", _format_rub(total_risk))
        c3.metric("Средний NPS", "—" if pd.isna(avg_nps_from_feedback) else f"{avg_nps_from_feedback:.1f}")

        auto_pct = compute_automation_pct(df_f)
        if auto_pct is None:
            st.metric(
                "Процент автоматизации",
                "—",
                help=f"Нужна колонка «{COL_PREP_METHOD}» и непустые значения.",
            )
        else:
            st.metric(
                "Процент автоматизации",
                f"{auto_pct * 100:.1f}%",
                help="Доля документов через «Конструктор» или «Шаблон» (без учёта регистра).",
            )

        st.markdown("#### Нагрузка на юристов")
        counts, latest = lawyer_workload_latest_month(df_f)
        if counts is None:
            st.caption("Нужны колонки «Дата» и «Ответственный юрист», а также даты в выбранном периоде.")
        else:
            st.caption(
                f"Последний месяц в данных: {latest.strftime('%Y-%m')}. "
                "Красный столбик — > 15 документов в месяц на юриста."
            )
            st.plotly_chart(workload_plotly_figure(counts), use_container_width=True)

        st.markdown("#### Время согласования по типам договоров")
        by_type = (
            df_f.groupby("Тип договора", dropna=False)["Дней на согласование"]
            .mean()
            .sort_values(ascending=False)
        )
        if by_type.empty:
            st.warning("Нет данных по выбранным фильтрам.")
        else:
            st.bar_chart(by_type, height=420)

        with st.expander("Данные (после фильтра)", expanded=False):
            st.dataframe(df_f, use_container_width=True, hide_index=True)

    with tab_feedback:
        st.markdown("#### Оцените работу сервиса")
        with st.form("feedback_form", clear_on_submit=True, border=True):
            lawyer = st.selectbox("Юрист", ["Анна Смирнова", "Иван Петров", "Мария Кузнецова"])
            score = st.slider("Оценка", min_value=1, max_value=10, value=8)
            comment = st.text_area("Комментарий", placeholder="Что было хорошо? Что можно улучшить?")
            submitted = st.form_submit_button("Отправить отзыв", type="primary")

        if submitted:
            try:
                save_feedback(lawyer=lawyer, score=score, comment=comment.strip())
                load_feedback_csv.clear()
            except Exception as e:
                st.error(f"Не удалось сохранить отзыв: {e}")
            else:
                st.success("Спасибо за вашу оценку!")

    with tab_goals:
        st.markdown("#### Action Plan на квартал")

        contracts_df: pd.DataFrame | None = None
        try:
            contracts_df = load_contracts_xlsx("data.xlsx")
        except FileNotFoundError:
            contracts_df = None
        except Exception:
            contracts_df = None

        missing_contract_cols: list[str] = []
        df_g: pd.DataFrame | None = None
        if contracts_df is not None:
            missing_contract_cols = _validate_columns(contracts_df)
            if not missing_contract_cols:
                df_g = contracts_df.copy()
                df_g["Дата"] = pd.to_datetime(df_g["Дата"], errors="coerce")
                df_g["Тип договора"] = df_g["Тип договора"].astype(str).str.strip()
                df_g["Дней на согласование"] = pd.to_numeric(df_g["Дней на согласование"], errors="coerce")
                df_g["Сумма риска (руб)"] = pd.to_numeric(df_g["Сумма риска (руб)"], errors="coerce")
                df_g["Оценка бизнеса"] = pd.to_numeric(df_g["Оценка бизнеса"], errors="coerce")
                if COL_PREP_METHOD in df_g.columns:
                    df_g[COL_PREP_METHOD] = df_g[COL_PREP_METHOD].astype(str).str.strip()
                if COL_LAWYER in df_g.columns:
                    df_g[COL_LAWYER] = df_g[COL_LAWYER].astype(str).str.strip()

                selected_types = st.session_state.get("filter_contract_types", None)
                if selected_types is None:
                    all_types = sorted([t for t in df_g["Тип договора"].dropna().unique().tolist() if t])
                    selected_types = all_types

                if selected_types:
                    df_g = df_g[df_g["Тип договора"].isin(selected_types)].copy()
                else:
                    df_g = df_g.iloc[0:0].copy()

        avg_days_all = float("nan")
        risk_total_all = float("nan")
        if df_g is not None:
            avg_days_all = df_g["Дней на согласование"].mean(skipna=True)
            risk_total_all = df_g["Сумма риска (руб)"].sum(skipna=True)

        nps_scores = feedback_df["score"] if "score" in feedback_df.columns else pd.Series(dtype=float)
        nps_count = int(nps_scores.notna().sum())
        avg_nps_for_goals = float(nps_scores.mean(skipna=True)) if nps_count else float("nan")

        automation_pct = compute_automation_pct(df_g) if df_g is not None else None
        workload_counts, workload_month = lawyer_workload_latest_month(df_g) if df_g is not None else (None, None)
        overload_any = bool(workload_counts is not None and bool(workload_counts["overload"].any()))

        target_days = 3.0
        target_nps = 9.0
        risk_kpi_rub = 10_000_000.0
        target_automation = 0.80

        has_speed = df_g is not None and not pd.isna(avg_days_all)
        has_risk = df_g is not None and not pd.isna(risk_total_all)
        has_nps = nps_count > 0 and not pd.isna(avg_nps_for_goals)
        has_automation = automation_pct is not None
        has_balance = workload_counts is not None

        speed_progress = float("nan")
        if has_speed:
            speed_progress = 1.0 if avg_days_all <= target_days else float(target_days / avg_days_all)

        nps_progress = float("nan")
        if has_nps:
            nps_progress = max(0.0, min(1.0, float(avg_nps_for_goals / target_nps)))

        risk_progress = float("nan")
        if has_risk:
            risk_progress = max(0.0, min(1.0, float(risk_total_all / risk_kpi_rub)))

        routine_progress = float("nan")
        if has_automation:
            routine_progress = max(0.0, min(1.0, float(automation_pct / target_automation)))

        balance_progress = float("nan")
        if has_balance:
            balance_progress = 0.0 if overload_any else 1.0

        can_compute_goals = has_speed and has_nps and has_risk and has_automation and has_balance

        st.markdown("### Автоматические рекомендации")
        recs: list[tuple[str, str, str]] = []

        if not pd.isna(avg_days_all) and avg_days_all > 5:
            recs.append(
                (
                    "Критично",
                    "Цель: Сократить Time-to-Contract.",
                    "Рекомендация: внедрить конструктор договоров и шаблоны согласования для типовых кейсов.",
                )
            )
        if not pd.isna(avg_nps_for_goals) and avg_nps_for_goals < 7:
            recs.append(
                (
                    "В работе",
                    "Цель: Поднять удовлетворённость внутреннего клиента.",
                    "Рекомендация: сократить количество итераций правок (SLA на правки, чек-лист входных данных).",
                )
            )
        if has_risk and risk_total_all <= 0:
            recs.append(
                (
                    "В работе",
                    "Цель: Повысить прозрачность предотвращённых рисков.",
                    "Рекомендация: стандартизировать фиксацию риска в `data.xlsx` и обязать заполнение поля суммы риска.",
                )
            )
        if has_automation and automation_pct is not None and automation_pct < 0.5:
            recs.append(
                (
                    "Критично",
                    "Цель: Снизить рутину в подготовке документов.",
                    "Рекомендация: расширить библиотеку шаблонов и подключить конструктор для топ‑типов договоров.",
                )
            )
        if has_balance and overload_any:
            recs.append(
                (
                    "Критично",
                    "Цель: Сбалансировать нагрузку на юристов.",
                    "Рекомендация: перераспределить потоки, ввести triage и правила эскалации при перегрузке (>15 док/мес).",
                )
            )

        if contracts_df is None:
            st.info("Для рекомендаций по договорам создайте `data.xlsx`.")
        elif missing_contract_cols:
            st.info(
                "В `data.xlsx` не хватает колонок для рекомендаций по договорам: "
                + ", ".join(f"‘{c}’" for c in missing_contract_cols)
            )

        if not recs:
            st.markdown(
                '<div class="action-card">Сигналы по данным не выявили критичных отклонений. '
                "Продолжайте мониторинг показателей и уточняйте OKR.</div>",
                unsafe_allow_html=True,
            )
        else:
            for status, goal, rec in recs:
                cls = "pill-work"
                if status == "Выполнено":
                    cls = "pill-done"
                if status == "Критично":
                    cls = "pill-crit"
                st.markdown(
                    f"""
                    <div class="action-card">
                      <div><span class="pill {cls}">{status}</span></div>
                      <div style="margin-top:0.5rem;"><b>{goal}</b></div>
                      <div style="margin-top:0.25rem; opacity:0.9;">{rec}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown("### OKR (Objectives & Key Results)")
        if not can_compute_goals:
            st.warning("Недостаточно данных для расчета целей")
        else:
            okrs: list[dict] = [
                {
                    "id": "goal_speed",
                    "title": "Скорость сервиса",
                    "status": "Выполнено" if speed_progress >= 1.0 else ("Критично" if speed_progress < 0.5 else "В работе"),
                    "progress": speed_progress,
                    "krs": [
                        f"Факт: среднее время согласования — {avg_days_all:.1f} дн.",
                        f"Цель: ≤ {target_days:.0f} дн.",
                    ],
                },
                {
                    "id": "goal_nps",
                    "title": "Качество поддержки (NPS)",
                    "status": "Выполнено" if nps_progress >= 1.0 else ("Критично" if nps_progress < 0.5 else "В работе"),
                    "progress": nps_progress,
                    "krs": [
                        f"Факт: средняя оценка из отзывов — {avg_nps_for_goals:.2f} ({nps_count} отзывов)",
                        f"Цель: {target_nps:.1f} баллов",
                    ],
                },
                {
                    "id": "goal_risk",
                    "title": "Контроль рисков",
                    "status": "Выполнено" if risk_progress >= 1.0 else ("Критично" if risk_progress < 0.5 else "В работе"),
                    "progress": risk_progress,
                    "krs": [
                        f"Факт: сумма риска в системе — {_format_rub(risk_total_all)}",
                        f"KPI: {_format_rub(risk_kpi_rub)}",
                    ],
                },
                {
                    "id": "goal_routine",
                    "title": "Снижение рутины",
                    "status": "Выполнено" if routine_progress >= 1.0 else ("Критично" if routine_progress < 0.5 else "В работе"),
                    "progress": routine_progress,
                    "krs": [
                        f"Факт: автоматизация — {automation_pct * 100:.1f}% (Конструктор/Шаблон)",
                        f"Цель: {target_automation * 100:.0f}%",
                    ],
                },
                {
                    "id": "goal_balance",
                    "title": "Баланс нагрузки",
                    "status": "Выполнено" if balance_progress >= 1.0 else ("Критично" if balance_progress < 0.5 else "В работе"),
                    "progress": balance_progress,
                    "krs": [
                        f"Месяц: {workload_month.strftime('%Y-%m') if workload_month is not None else '—'}",
                        "Правило: нет юристов с > 15 документами в месяц",
                    ],
                },
            ]

            status_class = {"В работе": "pill-work", "Выполнено": "pill-done", "Критично": "pill-crit"}

            for okr in okrs:
                done_key = f"okr_done_{okr['id']}"
                if done_key not in st.session_state:
                    st.session_state[done_key] = False

                left, right = st.columns([0.62, 0.38])
                with left:
                    st.checkbox(
                        "В фокусе на квартал",
                        key=done_key,
                        help="Отметка для команды — не влияет на автоматический прогресс.",
                    )
                    st.markdown(f"**{okr['title']}**")
                    cls = status_class.get(okr["status"], "pill-work")
                    st.markdown(f'<span class="pill {cls}">{okr["status"]}</span>', unsafe_allow_html=True)
                    with st.expander("Key Results", expanded=False):
                        for kr in okr["krs"]:
                            st.markdown(f"- {kr}")
                with right:
                    p = float(okr["progress"])
                    st.markdown(_progress_bar_html(p), unsafe_allow_html=True)
                    if okr["id"] == "goal_risk":
                        pct_of_kpi = int(round(max(0.0, min(1.0, p)) * 100))
                        st.caption(f"Зафиксировано в системе: {pct_of_kpi}% от KPI ({_format_rub(risk_kpi_rub)})")
                    elif okr["id"] == "goal_nps":
                        st.caption(f"Прогресс к цели: {avg_nps_for_goals:.2f} / {target_nps:.1f}")
                    elif okr["id"] == "goal_routine":
                        st.caption(f"Прогресс к цели: {(automation_pct or 0.0) * 100:.1f}% / {target_automation * 100:.0f}%")
                    elif okr["id"] == "goal_balance":
                        st.caption("Выполнено, если нет перегрузки (>15 док/мес) ни у одного юриста")
                    else:
                        st.caption(f"Прогресс к цели: {int(round(max(0.0, min(1.0, p)) * 100))}%")

    with tab_ip:
        st.header("IP • Мониторинг товарных знаков")
    
        try:
            df_ip = load_ip_xlsx()
            
            if df_ip.empty:
                st.warning("Нет данных по товарным знакам")
            else:
                # 2. KPI Карточки
                col1, col2, col3 = st.columns(3)
                col1.metric("Всего ТЗ", len(df_ip))
                
                in_progress = len(df_ip[df_ip['Статус'].isin(['В работе', 'Подана заявка'])])
                col2.metric("На регистрации", in_progress)
                
                # Расчет продлений
                df_ip['Продление'] = pd.to_datetime(df_ip['Продление'])
                days_to_renew = 180
                critical_date = datetime.now() + timedelta(days=days_to_renew)
                to_renew_count = len(df_ip[df_ip['Продление'] <= critical_date])
                col3.metric("Требуют продления", to_renew_count)

                # 3. График иностранных ТЗ (без РФ)
                df_foreign = df_ip[df_ip['Страна'] != 'РФ']
                if not df_foreign.empty:
                    fig_foreign = px.bar(
                        df_foreign['Страна'].value_counts().reset_index(),
                        x='count', y='Страна', orientation='h',
                        title="География иностранных ТЗ",
                        labels={'count': 'Количество', 'Страна': 'Страна'}
                    )
                    st.plotly_chart(fig_foreign)

                # 4. Таблица с аналитикой
                def highlight_expiry(row):
                    if pd.notna(row['Продление']) and row['Продление'] <= critical_date:
                        return ['background-color: #ffcccc'] * len(row)
                    return [''] * len(row)

                st.write("Реестр товарных знаков:")
                
                df_display = df_ip.copy()
                # Форматируем даты для удобства юристов
                df_display['Продление'] = df_display['Продление'].dt.strftime('%d.%m.%Y')
                df_display['Дата приоритета'] = pd.to_datetime(df_display['Дата приоритета']).dt.strftime('%d.%m.%Y')
                
                st.dataframe(df_display.style.apply(highlight_expiry, axis=1))

        except Exception as e:
            st.error(f"Ошибка во вкладке IP: {e}")

if __name__ == "__main__":
    main()
