from datetime import datetime

from services.export import (
    SECTION_SPECS,
    arabic_report_date,
    build_csv_document,
    build_excel_workbook,
    build_report,
    build_word_document,
)


SAMPLE = {
    "results": [
        {
            "title": "وزير العمل يعلن قرارات جديدة",
            "source": "google",
            "url": "https://www.molsa.gov.iq/minister",
        },
        {
            "title": "وزارة العمل تطلق خدمة جديدة",
            "source": "agencies",
            "platform": "nina",
            "agency_label": "نينا",
            "url": "https://www.ninanews.com/service",
        },
        {
            "title": "منشور رسمي عن الوزارة",
            "source": "facebook",
            "platform": "facebook",
            "is_social_mention": True,
            "url": "https://www.facebook.com/molsa/posts/1",
        },
        {
            "title": "احتجاج أمام الوزارة",
            "source": "google",
            "url": "https://example.com/protest",
        },
        {
            "title": "اجتماع منظمة العمل الدولية",
            "source": "ilo.org",
            "url": "https://www.ilo.org/meeting",
        },
    ]
}


def test_arabic_date_matches_attached_form():
    when = datetime(2026, 9, 6)
    assert arabic_report_date(when) == "الاحد6/9/2026"


def test_report_has_all_template_sections_and_headers():
    report = build_report(SAMPLE, datetime(2026, 9, 6))
    assert report.date_label == "الاحد6/9/2026"
    assert [(s.key, s.title, s.headers) for s in report.sections] == list(SECTION_SPECS)


def test_results_fill_the_same_three_columns():
    report = build_report(SAMPLE)
    by_key = {section.key: section.rows for section in report.sections}
    assert by_key["minister"][0][1] == "وزير العمل يعلن قرارات جديدة"
    assert by_key["agencies"][0] == ("1-", "وزارة العمل تطلق خدمة جديدة", "نينا")
    assert by_key["social"][0] == ("1-", "منشور رسمي عن الوزارة", "فيسبوك")
    assert by_key["negative"][0][1] == "احتجاج أمام الوزارة"
    assert by_key["international"][0][1] == "اجتماع منظمة العمل الدولية"
    assert by_key["subtitles"] == [("1-", "", "")]


def test_csv_uses_the_word_form():
    text = build_csv_document(SAMPLE, datetime(2026, 9, 6)).decode("utf-8-sig")
    assert "الاحد6/9/2026" in text
    assert "(اخـــبــار الــســيــد الــوزيــر)" in text
    assert "عنوان الخبر" in text
    assert "اسم الموقع" in text
    assert "السبتايتلات" in text
    assert "رصد الاخبار السلبية" in text
    assert "الشأن الدولي" in text


def test_excel_and_word_are_binary_office_files():
    xlsx = build_excel_workbook(SAMPLE, datetime(2026, 9, 6))
    docx = build_word_document(SAMPLE, datetime(2026, 9, 6))
    assert xlsx[:2] == b"PK"
    assert docx[:2] == b"PK"
