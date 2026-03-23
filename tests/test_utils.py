from rataGUI.utils import slugify


class TestSlugify:
    def test_basic(self):
        assert slugify("Hello World") == "Hello-World"

    def test_special_chars(self):
        assert slugify("hello!@#$%world") == "helloworld"

    def test_unicode_stripped(self):
        result = slugify("héllo wörld")
        assert result == "hello-world"

    def test_unicode_kept(self):
        result = slugify("héllo", allow_unicode=True)
        assert "héllo" == result

    def test_leading_trailing_dashes(self):
        assert slugify("--hello--") == "hello"

    def test_multiple_dashes(self):
        assert slugify("a---b") == "a-b"

    def test_empty_string(self):
        assert slugify("") == ""

    def test_numeric_input(self):
        assert slugify(42) == "42"

    def test_spaces_to_dashes(self):
        assert slugify("hello   world") == "hello-world"

    def test_underscores_preserved(self):
        assert slugify("hello_world") == "hello_world"

    def test_leading_trailing_underscores_stripped(self):
        assert slugify("__hello__") == "hello"

    def test_mixed_whitespace(self):
        assert slugify("hello\t\nworld") == "hello-world"
