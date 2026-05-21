from lc_auto.catalog import ProblemCatalog


def test_catalog_parses_numeric_frontend_ids_only():
    catalog = ProblemCatalog.from_api_payload(
        {
            "stat_status_pairs": [
                {
                    "stat": {
                        "frontend_question_id": "1",
                        "question__title_slug": "two-sum",
                        "question__title": "Two Sum",
                    },
                    "paid_only": False,
                    "difficulty": {"level": 1},
                },
                {
                    "stat": {
                        "frontend_question_id": "LCP 82",
                        "question__title_slug": "cnHoX6",
                        "question__title": "万灵之树",
                    },
                    "paid_only": False,
                    "difficulty": {"level": 3},
                },
                {
                    "stat": {
                        "frontend_question_id": "2",
                        "question__title_slug": "hidden-problem",
                        "question__title": "Hidden",
                        "question__hide": True,
                    },
                    "paid_only": False,
                    "difficulty": {"level": 2},
                },
            ]
        }
    )

    assert catalog.get(1).slug == "two-sum"
    assert catalog.get(1).difficulty == "easy"
    assert catalog.get(82) is None
    assert catalog.get(2) is None
