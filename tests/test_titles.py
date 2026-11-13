"""Readable titles for votes Voteview's older records type in capitals."""

from congress_congruence.api.titles import is_shouting, tidy


def test_capitals_become_sentence_case_with_proper_names_kept():
    assert tidy("TO ELECT THE SPEAKER OF THE HOUSE OF REPRESENTATIVES FOR THE 93RD CONGRESS.") == \
        "To elect the Speaker of the House of Representatives for the 93rd Congress."
    assert tidy("TO ORDER THE PREVIOUS QUESTION ON H.RES. 6, ADOPTION OF THE RULES OF THE HOUSE.") == \
        "To order the previous question on H.Res. 6, adoption of the rules of the House."
    assert tidy("TO CONFIRM THE NOMINATION OF WILLIAM P. CLEMENTS, JR., OF TEXAS TO BE DEPUTY SECRETARY "
                "OF DEFENSE IN THE DEPARTMENT OF DEFENSE.") == \
        ("To confirm the nomination of William P. Clements, Jr., of Texas to be deputy secretary of Defense "
         "in the Department of Defense.")
    assert tidy("TO PASS S. 1234, AMENDING THE SOCIAL SECURITY ACT. IT FUNDS NASA AND THE U.S. COAST GUARD "
                "IN NEW YORK.") == \
        "To pass S. 1234, amending the Social Security Act. It funds NASA and the U.S. Coast Guard in New York."
    assert tidy("TO AGREE TO H.J.RES. 542 AND S.CON.RES. 12 OVER THE PRESIDENT'S VETO.") == \
        "To agree to H.J.Res. 542 and S.Con.Res. 12 over the President's veto."
    assert tidy("TO STRIKE TITLE IX AND THE STATE GRANTS; SECRETARY OF STATE.") == \
        "To strike Title IX and the state grants; secretary of State."


def test_text_not_in_capitals_is_left_alone():
    for text in ("On Motion to Table the Amendment", "H.R. 1: For the People Act of 2021", None, "", "ON PASSAGE"):
        assert tidy(text) == text or (text == "ON PASSAGE" and tidy(text) == "On passage")
    assert not is_shouting("Passed") and is_shouting("ON THE AMENDMENT")
