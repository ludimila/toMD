from tomd.updates import is_newer, parse_version


def test_ordenacao_numerica_nao_lexicografica():
    assert is_newer("1.1", "1.0")
    assert is_newer("1.10", "1.1")
    assert not is_newer("1.1", "1.10")
    assert is_newer("2.0", "1.10")


def test_ignora_prefixo_v():
    assert is_newer("v1.2", "1.1")
    assert parse_version("v1.2") == (1, 2)
    assert parse_version("V1.2") == (1, 2)


def test_igual_nao_e_mais_nova():
    assert not is_newer("1.1", "1.1")
    assert not is_newer("v1.1", "1.1")
    assert not is_newer("1.1.0", "1.1")


def test_tag_invalida_e_ignorada():
    assert not is_newer("beta", "1.1")
    assert not is_newer("", "1.1")
