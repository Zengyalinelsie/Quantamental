"""Bounded official identity evidence for CSI history gaps.

The records in this module are current retrieval evidence, not point-in-time
identity observations.  They exist only to resolve the finite set of delisted
codes found while rebuilding the normalized-current CSI 300/500 history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True)
class OfficialDelistedIdentity:
    code: str
    legal_name: str
    listed_on: date
    delisted_on: date
    listing_source_id: str
    legal_name_source_id: str
    listing_source_url: str
    legal_name_source_url: str
    security_name: str | None = None


_SSE_SOURCE_URL = "https://www.sse.com.cn/assortment/stock/list/delisting/"
_SZSE_SOURCE_URL = "https://www.szse.cn/market/stock/suspend/index.html"
_CNINFO_SOURCE_URL = "https://www.cninfo.com.cn/new/disclosure"


def _sse(
    code: str,
    legal_name: str,
    listed_on: date,
    delisted_on: date,
) -> OfficialDelistedIdentity:
    return OfficialDelistedIdentity(
        code=code,
        legal_name=legal_name,
        listed_on=listed_on,
        delisted_on=delisted_on,
        listing_source_id="sse.delisted_company_list",
        legal_name_source_id="sse.delisted_company_list",
        listing_source_url=_SSE_SOURCE_URL,
        legal_name_source_url=_SSE_SOURCE_URL,
    )


def _szse(
    code: str,
    legal_name: str,
    listed_on: date,
    delisted_on: date,
    *,
    report_year: int = 2018,
    announcement_id: str | None = None,
    security_name: str | None = None,
) -> OfficialDelistedIdentity:
    legal_name_source_id = f"cninfo.{report_year}_annual_report_cover:{code}"
    if announcement_id is not None:
        legal_name_source_id += f":{announcement_id}"
    return OfficialDelistedIdentity(
        code=code,
        legal_name=legal_name,
        listed_on=listed_on,
        delisted_on=delisted_on,
        listing_source_id="szse.delisted_company_list",
        legal_name_source_id=legal_name_source_id,
        listing_source_url=_SZSE_SOURCE_URL,
        legal_name_source_url=_CNINFO_SOURCE_URL,
        security_name=security_name,
    )


_IDENTITIES = (
    _sse(
        "SH.600068",
        "中国葛洲坝集团股份有限公司",
        date(1997, 5, 26),
        date(2021, 9, 13),
    ),
    _sse(
        "SH.600074",
        "江苏保千里视像科技集团股份有限公司",
        date(1997, 6, 23),
        date(2020, 6, 3),
    ),
    _sse(
        "SH.600297",
        "广汇汽车服务集团股份公司",
        date(2000, 11, 16),
        date(2024, 8, 28),
    ),
    _sse(
        "SH.600485",
        "北京信威科技集团股份有限公司",
        date(2003, 8, 7),
        date(2021, 6, 1),
    ),
    _sse(
        "SH.600705",
        "中航工业产融控股股份有限公司",
        date(1996, 5, 16),
        date(2025, 5, 27),
    ),
    _sse(
        "SH.600804",
        "鹏博士电信传媒集团股份有限公司",
        date(1994, 1, 3),
        date(2025, 7, 3),
    ),
    _sse(
        "SH.600837",
        "海通证券股份有限公司",
        date(1994, 2, 24),
        date(2025, 3, 4),
    ),
    _sse(
        "SH.601989",
        "中国船舶重工股份有限公司",
        date(2009, 12, 16),
        date(2025, 9, 5),
    ),
    _szse(
        "SZ.000413",
        "东旭光电科技股份有限公司",
        date(1996, 9, 25),
        date(2024, 10, 11),
    ),
    _szse(
        "SZ.000540",
        "中天金融集团股份有限公司",
        date(1994, 2, 2),
        date(2023, 6, 30),
    ),
    _szse(
        "SZ.000627",
        "天茂实业集团股份有限公司",
        date(1996, 11, 12),
        date(2025, 9, 30),
    ),
    _szse(
        "SZ.000671",
        "阳光城集团股份有限公司",
        date(1996, 12, 18),
        date(2023, 8, 16),
    ),
    _szse(
        "SZ.000961",
        "江苏中南建设集团股份有限公司",
        date(2000, 3, 1),
        date(2024, 7, 11),
    ),
    _szse(
        "SZ.002411",
        "延安必康制药股份有限公司",
        date(2010, 5, 25),
        date(2023, 7, 12),
    ),
    _szse(
        "SZ.002450",
        "康得新复合材料集团股份有限公司",
        date(2010, 7, 16),
        date(2021, 5, 31),
    ),
    _sse(
        "SH.600086",
        "东方金钰股份有限公司",
        date(1997, 6, 6),
        date(2021, 3, 18),
    ),
    _sse(
        "SH.600122",
        "江苏宏图高科技股份有限公司",
        date(1998, 4, 20),
        date(2023, 6, 26),
    ),
    _sse(
        "SH.600240",
        "北京华业资本控股股份有限公司",
        date(2000, 6, 28),
        date(2020, 2, 6),
    ),
    _sse(
        "SH.600260",
        "湖北凯乐科技股份有限公司",
        date(2000, 7, 6),
        date(2023, 2, 15),
    ),
    _sse(
        "SH.600270",
        "中外运空运发展股份有限公司",
        date(2000, 12, 28),
        date(2018, 12, 28),
    ),
    _sse(
        "SH.600277",
        "亿利洁能股份有限公司",
        date(2000, 7, 25),
        date(2024, 7, 18),
    ),
    _sse(
        "SH.600291",
        "内蒙古西水创业股份有限公司",
        date(2000, 7, 31),
        date(2022, 6, 14),
    ),
    _sse(
        "SH.600317",
        "营口港务股份有限公司",
        date(2002, 1, 31),
        date(2021, 1, 29),
    ),
    _sse(
        "SH.600393",
        "广州粤泰集团股份有限公司",
        date(2001, 3, 19),
        date(2023, 7, 18),
    ),
    _sse(
        "SH.600466",
        "四川蓝光发展股份有限公司",
        date(2001, 2, 12),
        date(2023, 6, 6),
    ),
    _sse(
        "SH.600565",
        "重庆市迪马实业股份有限公司",
        date(2002, 7, 23),
        date(2024, 8, 7),
    ),
    _sse(
        "SH.600614",
        "鹏起科技发展股份有限公司",
        date(1992, 8, 28),
        date(2021, 7, 22),
    ),
    _sse(
        "SH.600687",
        "甘肃刚泰控股(集团)股份有限公司",
        date(1993, 11, 8),
        date(2021, 3, 4),
    ),
    _sse(
        "SH.600811",
        "东方集团股份有限公司",
        date(1994, 1, 6),
        date(2025, 4, 30),
    ),
    _sse(
        "SH.600823",
        "上海世茂股份有限公司",
        date(1994, 2, 4),
        date(2024, 6, 14),
    ),
    _sse(
        "SH.600978",
        "宜华生活科技股份有限公司",
        date(2004, 8, 24),
        date(2021, 3, 22),
    ),
    _sse(
        "SH.603056",
        "德邦物流股份有限公司",
        date(2018, 1, 16),
        date(2026, 3, 31),
    ),
    _szse(
        "SZ.000418",
        "无锡小天鹅股份有限公司",
        date(1997, 3, 28),
        date(2019, 6, 21),
        announcement_id="1205963284",
    ),
    _szse(
        "SZ.000587",
        "金洲慈航集团股份有限公司",
        date(1996, 4, 25),
        date(2023, 4, 3),
        announcement_id="1206164294",
    ),
    _szse(
        "SZ.000662",
        "天夏智慧城市科技股份有限公司",
        date(1996, 12, 16),
        date(2021, 4, 12),
        announcement_id="1206400061",
    ),
    _szse(
        "SZ.000667",
        "美好置业集团股份有限公司",
        date(1996, 12, 5),
        date(2023, 7, 14),
        announcement_id="1205856261",
    ),
    _szse(
        "SZ.000732",
        "泰禾集团股份有限公司",
        date(1997, 7, 4),
        date(2023, 8, 4),
        announcement_id="1206016010",
    ),
    _szse(
        "SZ.000806",
        "北海银河生物产业投资股份有限公司",
        date(1998, 4, 16),
        date(2023, 7, 6),
        announcement_id="1206368347",
    ),
    _szse(
        "SZ.000939",
        "凯迪生态环境科技股份有限公司",
        date(1999, 9, 23),
        date(2020, 12, 17),
        announcement_id="1206126414",
    ),
    _szse(
        "SZ.000979",
        "中弘控股股份有限公司",
        date(2000, 6, 16),
        date(2018, 12, 28),
        report_year=2017,
        announcement_id="1205090397",
    ),
    _szse(
        "SZ.002002",
        "鸿达兴业股份有限公司",
        date(2004, 6, 25),
        date(2024, 3, 18),
        announcement_id="1206071415",
    ),
    _szse(
        "SZ.002013",
        "中航工业机电系统股份有限公司",
        date(2004, 7, 5),
        date(2023, 3, 17),
        announcement_id="1205899794",
    ),
    _szse(
        "SZ.002018",
        "安徽华信国际控股股份有限公司",
        date(2004, 7, 13),
        date(2019, 11, 1),
        announcement_id="1206243307",
    ),
    _szse(
        "SZ.002118",
        "吉林紫鑫药业股份有限公司",
        date(2007, 3, 2),
        date(2023, 8, 4),
        announcement_id="1206243095",
    ),
    _szse(
        "SZ.002147",
        "新光圆成股份有限公司",
        date(2007, 8, 8),
        date(2022, 6, 23),
        announcement_id="1206121910",
    ),
    _szse(
        "SZ.002280",
        "杭州联络互动信息科技股份有限公司",
        date(2009, 8, 21),
        date(2024, 8, 16),
        announcement_id="1206374821",
    ),
    _szse(
        "SZ.002308",
        "威创集团股份有限公司",
        date(2009, 11, 27),
        date(2024, 9, 27),
        announcement_id="1206046817",
    ),
    _szse(
        "SZ.002325",
        "深圳洪涛集团股份有限公司",
        date(2009, 12, 22),
        date(2024, 8, 15),
        announcement_id="1206124895",
    ),
    _szse(
        "SZ.002359",
        "北讯集团股份有限公司",
        date(2010, 2, 10),
        date(2021, 7, 23),
        announcement_id="1206254240",
    ),
    _szse(
        "SZ.002477",
        "雏鹰农牧集团股份有限公司",
        date(2010, 9, 15),
        date(2019, 10, 16),
        announcement_id="1206091330",
    ),
    _szse(
        "SZ.002503",
        "搜于特集团股份有限公司",
        date(2010, 11, 17),
        date(2023, 8, 11),
        announcement_id="1206021518",
    ),
    _szse(
        "SZ.002505",
        "湖南大康国际农业食品股份有限公司",
        date(2010, 11, 18),
        date(2024, 8, 30),
        announcement_id="1206123983",
    ),
    _szse(
        "SZ.002509",
        "天广中茂股份有限公司",
        date(2010, 11, 23),
        date(2020, 7, 20),
        announcement_id="1206475803",
    ),
    _szse(
        "SZ.002665",
        "北京首航艾启威节能技术股份有限公司",
        date(2012, 3, 27),
        date(2024, 8, 26),
        announcement_id="1206257670",
    ),
    _szse(
        "SZ.002699",
        "美盛文化创意股份有限公司",
        date(2012, 9, 11),
        date(2024, 6, 5),
        announcement_id="1206253811",
    ),
    _szse(
        "SZ.300116",
        "陕西坚瑞沃能股份有限公司",
        date(2010, 9, 2),
        date(2024, 7, 25),
        announcement_id="1206166266",
    ),
    _szse(
        "SZ.300156",
        "神雾环保技术股份有限公司",
        date(2011, 1, 7),
        date(2020, 8, 25),
        announcement_id="1206320345",
    ),
    _szse(
        "SZ.300202",
        "聚龙股份有限公司",
        date(2011, 4, 15),
        date(2022, 7, 4),
        announcement_id="1206088961",
    ),
    _szse(
        "SZ.300273",
        "珠海和佳医疗设备股份有限公司",
        date(2011, 10, 26),
        date(2023, 7, 6),
        announcement_id="1206107776",
    ),
    _szse(
        "SZ.300297",
        "蓝盾信息安全技术股份有限公司",
        date(2012, 3, 15),
        date(2023, 7, 31),
        announcement_id="1206120101",
    ),
    _szse(
        "SZ.000046",
        "泛海控股股份有限公司",
        date(1994, 9, 12),
        date(2024, 2, 7),
        announcement_id="1206041336",
        security_name="*ST泛海",
    ),
    _szse(
        "SZ.300630",
        "海南普利制药股份有限公司",
        date(2017, 3, 28),
        date(2025, 5, 22),
        announcement_id="1205982204",
        security_name="普利退",
    ),
)

_IDENTITIES_BY_CODE = {item.code: item for item in _IDENTITIES}
if len(_IDENTITIES_BY_CODE) != len(_IDENTITIES):
    raise RuntimeError("official delisted identity evidence contains duplicate codes")

CSI_HISTORICAL_DELISTED_IDENTITIES: Final[
    Mapping[str, OfficialDelistedIdentity]
] = MappingProxyType(_IDENTITIES_BY_CODE)


def official_delisted_identity(code: str) -> OfficialDelistedIdentity | None:
    """Return official current evidence for a known finite CSI identity gap."""

    return CSI_HISTORICAL_DELISTED_IDENTITIES.get(code)
