from navimow_unofficial_const import canonical_region, passport_hosts, mower_hosts, DEFAULT_REGION


def test_default_region():
    assert DEFAULT_REGION == "fra"


def test_canonical_region_aliases():
    assert canonical_region("EU") == "fra"
    assert canonical_region("sea") == "sg"
    assert canonical_region("ore") == "us"
    assert canonical_region(None) == "fra"
    assert canonical_region("") == "fra"
    assert canonical_region("bj") == "bj"


def test_passport_hosts_known_region():
    hosts = passport_hosts("fra")
    assert hosts[0] == "api-passport-fra.willand.com"
    assert "api-passport-fra.ninebot.com" in hosts


def test_passport_hosts_unknown_region_falls_back_to_all():
    hosts = passport_hosts("does-not-exist")
    assert len(hosts) >= 4  # mindestens ein Host je bekannter Region


def test_mower_hosts_us_has_no_dedicated_host_but_falls_back():
    hosts = mower_hosts("us")
    assert "navimow-fra.ninebot.com" in hosts
