#!/usr/bin/env python
# encoding: utf-8
import re

from reporters_db import REPORTERS
from cl.citations.utils import map_reporter_db_cite_type
from cl.search.models import Citation as ModelCitation

"""
The classes in this module are not proper Django models; rather, they are just
convenience classes to help with citation extraction. None of these objects are
actually backed in the database; they just help with structuring and parsing
citation information and are discarded after use.
"""


class Citation(object):
    """Convenience class which represents a single citation found in a
    document.
    """

    def __init__(
        self,
        reporter,
        page,
        volume,
        canonical_reporter=None,
        lookup_index=None,
        extra=None,
        defendant=None,
        plaintiff=None,
        court=None,
        year=None,
        match_url=None,
        match_id=None,
        reporter_found=None,
        reporter_index=None,
    ):

        # Core data.
        self.reporter = reporter
        self.volume = volume
        self.page = page

        # These values are set during disambiguation.
        # For a citation to F.2d, the canonical reporter is F.
        self.canonical_reporter = canonical_reporter
        self.lookup_index = lookup_index

        # Supplementary data, if possible.
        self.extra = extra
        self.defendant = defendant
        self.plaintiff = plaintiff
        self.court = court
        self.year = year

        # The reporter found in the text is often different from the reporter
        # once it's normalized. We need to keep the original value so we can
        # linkify it with a regex.
        self.reporter_found = reporter_found

        # The location of the reporter is useful for tasks like finding
        # parallel citations, and finding supplementary info like defendants
        # and years.
        self.reporter_index = reporter_index

        # Attributes of the matching item, for URL generation.
        self.match_url = match_url
        self.match_id = match_id

        self.equality_attributes = [
            "reporter",
            "volume",
            "page",
            "canonical_reporter",
            "lookup_index",
        ]

    def as_regex(self):
        pass

    def as_html(self):
        pass

    def base_citation(self):
        return "%d %s %s" % (self.volume, self.reporter, self.page)

    def to_model(self):
        # Create a citation object as in our models. Eventually, the version in
        # our models should probably be the only object named "Citation". Until
        # then, this function helps map from this object to the Citation object
        # in the models.
        c = ModelCitation(
            **{
                key: value
                for key, value in self.__dict__.items()
                if key in ModelCitation._meta.get_all_field_names()
            }
        )
        canon = REPORTERS[self.canonical_reporter]
        cite_type = canon[self.lookup_index]["cite_type"]
        c.type = map_reporter_db_cite_type(cite_type)
        return c

    def __repr__(self):
        print_string = self.base_citation()
        if self.defendant:
            print_string = " ".join([self.defendant, print_string])
            if self.plaintiff:
                print_string = " ".join([self.plaintiff, "v.", print_string])
        if self.extra:
            print_string = " ".join([print_string, self.extra])
        if self.court and self.year:
            paren = "(%s %d)" % (self.court, self.year)
        elif self.year:
            paren = "(%d)" % self.year
        elif self.court:
            paren = "(%s)" % self.court
        else:
            paren = ""
        print_string = " ".join([print_string, paren])
        return print_string

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def fuzzy_hash(self):
        """Used to test equality in dicts.

        Overridden here to simplify away some of the attributes that can differ
        for the same citation.
        """
        s = ""
        for attr in self.equality_attributes:
            s += str(getattr(self, attr, None))
        return hash(s)

    def fuzzy_eq(self, other):
        """Used to override the __eq__ function."""
        return self.fuzzy_hash() == other.fuzzy_hash()


class FullCitation(Citation):
    """Convenience class which represents a standard, fully named citation,
    i.e., the kind of citation that marks the first time a document is cited.
    This kind of citation can be easily matched to an opinion in our database.

    Example: Adarand Constructors, Inc. v. Peña, 515 U.S. 200, 240
    """

    def __init__(self, *args, **kwargs):
        # Fully implements the standard Citation object.
        super(FullCitation, self).__init__(*args, **kwargs)

    def as_regex(self):
        return r"%d(\s+)%s(\s+)%s(\s?)" % (
            self.volume,
            re.escape(self.reporter_found),
            re.escape(self.page),
        )

    # TODO: Update css for no-link citations
    def as_html(self):
        # Uses reporter_found so that we don't update the text. This guards us
        # against accidentally updating things like docket number 22 Cr. 1 as
        # 22 Cranch 1, which is totally wrong.
        template = (
            '<span class="volume">%(volume)d</span>\\g<1>'
            '<span class="reporter">%(reporter)s</span>\\g<2>'
            '<span class="page">%(page)s</span>\\g<3>'
        )
        inner_html = template % self.__dict__
        span_class = "citation"
        if self.match_url:
            inner_html = '<a href="%s">%s</a>' % (self.match_url, inner_html)
            data_attr = ' data-id="%s"' % self.match_id
        else:
            span_class += " no-link"
            data_attr = ""
        return '<span class="%s"%s>%s</span>' % (
            span_class,
            data_attr,
            inner_html,
        )


class ShortformCitation(Citation):
    """Convenience class which represents a short form citation, i.e., the kind
    of citation made after a full citation has already appeared. This kind of
    citation lacks a full case name and usually has a different page number
    than the canonical citation, so this kind cannot be matched to an opinion
    directly. Instead, we will later try to resolve it to one of the foregoing
    full citations.

    Example 1: Adarand, 515 U.S., at 241
    Example 2: Adarand, 515 U.S. at 241
    Example 3: 515 U.S., at 241
    """

    def __init__(self, reporter, page, volume, antecedent_guess, **kwargs):
        # Like a Citation object, but we have to guess who the antecedent is
        # and the page number is non-canonical
        super(ShortformCitation, self).__init__(
            reporter, page, volume, **kwargs
        )

        self.antecedent_guess = antecedent_guess

    def __repr__(self):
        print_string = "%s, %d %s, at %s" % (
            self.antecedent_guess,
            self.volume,
            self.reporter,
            self.page,
        )
        return print_string

    def as_regex(self):
        return r"%s(\s+)%d(\s+)%s(,?)(\s+)at(\s+)%s(\s?)" % (
            re.escape(self.antecedent_guess),
            self.volume,
            re.escape(self.reporter_found),
            re.escape(self.page),
        )

    def as_html(self):
        # Don't include the antecedent guess in the HTML link, since the guess
        # might be horribly wrong.
        inner_html = (
            '<span class="volume">%(volume)d</span>\\g<2>'
            + '<span class="reporter">%(reporter)s</span>\\g<3>\\g<4>at\\g<5>'
            + '<span class="page">%(page)s</span>\\g<6>'
        )
        inner_html = inner_html % self.__dict__
        span_class = "citation"
        if self.match_url:
            inner_html = '<a href="%s">%s</a>' % (self.match_url, inner_html)
            data_attr = ' data-id="%s"' % self.match_id
        else:
            span_class += " no-link"
            data_attr = ""
        return (
            '<span class="%s"%s><span class="antecedent_guess">%s</span>\\g<1>%s</span>'
            % (span_class, data_attr, self.antecedent_guess, inner_html)
        )


class SupraCitation(Citation):
    """Convenience class which represents a 'supra' citation, i.e., a citation
    to something that is above in the document. Like a short form citation,
    this kind of citation lacks a full case name and usually has a different
    page number than the canonical citation, so this kind cannot be matched to
    an opinion directly. Instead, we will later try to resolve it to one of the
    foregoing full citations.

    Example 1: Adarand, supra, at 240
    Example 2: Adarand, 515 supra, at 240
    Example 3: Adarand, supra, somethingelse
    Example 4: Adarand, supra. somethingelse
    """

    def __init__(self, antecedent_guess, page=None, volume=None, **kwargs):
        # Like a Citation object, but without knowledge of the reporter or the
        # volume. Only has a guess at what the antecedent is.
        super(SupraCitation, self).__init__(None, page, volume, **kwargs)

        self.antecedent_guess = antecedent_guess

    def __repr__(self):
        print_string = "%s supra, at %s" % (self.antecedent_guess, self.page)
        return print_string

    def as_regex(self):
        if self.volume:
            s = r"%s(\s+)%d(\s+)supra" % (
                re.escape(self.antecedent_guess),
                self.volume,
            )
        else:
            s = r"%s(\s+)supra" % re.escape(self.antecedent_guess)

        if self.page:
            s += r",(\s+)at(\s+)%s" % re.escape(self.page)

        return s + r"(\s?)"

    def as_html(self):
        inner_html = (
            '<span class="antecedent_guess">%s</span>' % self.antecedent_guess
        )
        if self.volume:
            inner_html += (
                '\\g<1><span class="volume">%d</span>\\g<2>supra' % self.volume
            )
            if self.page:
                inner_html += (
                    ',\\g<3>at\\g<4><span class="page">%s</span>\\g<5>'
                    % self.page
                )
            else:
                inner_html += "\\g<3>"
        else:
            inner_html += "\\g<1>supra"
            if self.page:
                inner_html += (
                    ',\\g<2>at\\g<3><span class="page">%s</span>\\g<4>'
                    % self.page
                )
            else:
                inner_html += "\\g<2>"

        span_class = "citation"
        if self.match_url:
            inner_html = '<a href="%s">%s</a>' % (self.match_url, inner_html)
            data_attr = ' data-id="%s"' % self.match_id
        else:
            span_class += " no-link"
            data_attr = ""
        return '<span class="%s"%s>%s</span>' % (
            span_class,
            data_attr,
            inner_html,
        )


class IdCitation(Citation):
    """Convenience class which represents an 'id' or 'ibid' citation, i.e., a
    citation to the document referenced immediately prior. An 'id' citation is
    unlike a regular citation object since it has no knowledge of its reporter,
    volume, or page. Instead, the only helpful information that this reference
    possesses is a record of the tokens after the 'id' token. Those tokens
    enable us to build a regex to match this citation later.

    Example: "... foo bar," id., at 240
    """

    def __init__(self, id_token=None, after_tokens=None, should_linkify=False):
        super(IdCitation, self).__init__(None, None, None)

        self.id_token = id_token
        self.after_tokens = after_tokens

        # Whether the "after tokens" should be included in the generated link
        self.should_linkify = should_linkify

    def __repr__(self):
        print_string = "%s %s" % (self.id_token, self.after_tokens)
        return print_string

    def as_regex(self):
        # This works by matching only the Id. token that precedes the "after
        # tokens" we collected earlier.
        # The content matched by the matching groups in this regex will later
        # be re-injected into the generated HTML using backreferences

        # Whitespace regex explanation:
        #  \s matches any whitespace character
        #  </?\w+> matches any HTML tag
        #  , matches a comma
        #  The whole thing matches greedily, saved into a single group
        whitespace_regex = r"((?:\s|</?\w+>|,)*)"

        # Start with a matching group for any whitespace
        template = whitespace_regex

        # Add the id_token
        template += re.escape(self.id_token)

        # Add a matching group for any whitespace
        template += whitespace_regex

        # Add all the "after tokens", with whitespace groups in between
        template += whitespace_regex.join(
            [re.escape(t) for t in self.after_tokens]
        )

        # Add a final matching group for any non-HTML whitespace at the end
        template += r"(\s?)"

        return template

    def generate_after_token_html(self):
        # First, insert the regex backreferences between each "after token"
        # The group numbers of each backreference (g<NUMBER>) must be
        #   dynamically generated because total number of "after tokens" varies
        # Produces something like this:
        # "\\g<2>after_token_1\\g<3>after_token_2\\g<4>after_token_3" ...
        template = "\\g<%s>%s"
        after_token_html = "".join(
            [
                template % (str(i + 2), t)
                for i, t in enumerate(self.after_tokens)
            ]
        )

        # Then, append one final backreference to the end of the string
        after_token_html += "\\g<" + str(len(self.after_tokens) + 2) + ">"

        # Return the full string
        return after_token_html

    def as_html(self):
        span_class = "citation"
        after_token_html = self.generate_after_token_html()
        if self.match_url:
            if self.should_linkify:
                id_string_template = (
                    '<a href="%s"><span class="id_token">%s</span>%s</a>'
                )
            else:
                id_string_template = (
                    '<a href="%s"><span class="id_token">%s</span></a>%s'
                )
            id_string = id_string_template % (
                self.match_url,
                self.id_token,
                after_token_html,
            )
            data_attr = ' data-id="%s"' % self.match_id
        else:
            id_string = '<span class="id_token">%s</span>%s' % (
                self.id_token,
                after_token_html,
            )
            span_class += " no-link"
            data_attr = ""
        return '<span class="%s"%s>\\g<1>%s</span>' % (
            span_class,
            data_attr,
            id_string,
        )


class NonopinionCitation(object):
    """Convenience class which represents a citation to something that we know
    is not an opinion. This could be a citation to a statute, to the U.S. code,
    the U.S. Constitution, etc.

    Example 1: 18 U.S.C. §922(g)(1)
    Example 2: U. S. Const., Art. I, §8
    """

    def __init__(self, match_token):
        # TODO: Do something meaningful with this (e.g., extract the strings
        # surrounding the token to grab the full citation; linkify this
        # citation to an external source; etc.)
        self.match_token = match_token

    def __repr__(self):
        return "NonopinionCitation"

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)
