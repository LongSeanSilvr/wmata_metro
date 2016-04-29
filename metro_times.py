"""
This app returns train times for the Metro DC transit system.
"""

from __future__ import print_function
import httplib
import urllib
import json


# ======================================================================================================================
# Handler
# ======================================================================================================================
def lambda_handler(event, context=None):
    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])

    if event['session']['new']:
        on_session_started({'requestId': event['request']['requestId']},
                           event['session'])

    if event['request']['type'] == "LaunchRequest":
        return on_launch(event['request'], event['session'])
    elif event['request']['type'] == "IntentRequest":
        return on_intent(event['request'], event['session'])
    elif event['request']['type'] == "SessionEndedRequest":
        return on_session_ended(event['request'], event['session'])


# ======================================================================================================================
# Session Event Functions
# ======================================================================================================================
def on_session_started(session_started_request, session):
    print("on_session_started requestId={}, sessionId={}".format(session_started_request['requestId'],
                                                                 session['sessionId']))


def on_launch(launch_request, session):
    print("on_launch requestId={}, sessionId={}".format(launch_request['requestId'], session['sessionId']))
    return get_welcome_response()


def on_intent(intent_request, session):
    print("on_intent requestId={}, sessionId={}".format(intent_request['requestId'], session['sessionId']))
    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']
    if intent_name == "GetTimes":
        return get_times(intent, session)
    elif intent_name == "CommuteEstimate":
        return commute_estimate(intent, session)
    else:
        raise ValueError("Invalid intent")


def on_session_ended(session_ended_request, session):
    print(
        "on_session_ended requestId={}, sessionId={}".format(session_ended_request['requestId'], session['sessionId']))


# ======================================================================================================================
# Skill Behaviours -- Major Functions
# ======================================================================================================================
def get_welcome_response():
    card_title = "Welcome"
    session_attributes = {}
    speech_output = "Ok, ready to give you train times."
    reprompt_text = ("Ask for a train time by saying, for example, "
                     "when is the next train from Dupont Circle to Shady Grove?")
    should_end_session = False
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, should_end_session, reprompt_text))


def commute_estimate(intent, session):
    card_title = "commute_estimate"
    should_end_session = True
    session_attributes = {}
    station_data = get_stations()

    # Validate that user has given a source and destination, and that they are recognized stations
    try:
        st = get_equivalents(intent['slots']['source']['value'])
        station = name_lookup(st, station_data)
        if not station:
            speech_output = "Sorry, I don't recognize station {}.".format(st)
            print(speech_output)
            return build_response(session_attributes, build_speechlet_response(card_title, speech_output,
                                                                               should_end_session))
        dst = get_equivalents(intent['slots']['destination']['value'])
        destination = name_lookup(dst, station_data)
        if not destination:
            speech_output = "Sorry, I don't recognize station {}.".format(dst)
            print(speech_output)
            return build_response(session_attributes, build_speechlet_response(card_title, speech_output,
                                                                               should_end_session))
    except KeyError:
        speech_output = "To get travel times, you must specify an origin and a destination. For example, Say travel " \
                        "times from Dupont to Shady Grove."
        print(speech_output)
        return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, should_end_session))

    # Check for Farragut mixup
    station_options = get_options(station, station_data)
    if "farragut" in (station, destination):
        (station, destination) = which_farragut(station, destination, station_options, station_data)
        # recalculate station options
        station_options = get_options(station, station_data)
    destination_options = get_options(destination, station_data)

    estimate = retrieve_estimate(station_options, destination_options)
    speech_output = get_speech_output(estimate, station, destination)
    print(speech_output)
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, should_end_session))

def retrieve_estimate(station_options, destination_options):

    intersection = [x for x in station_options.keys() if x in destination_options.keys()]
    if not intersection:
        return "no_intersection"
    else:
        shared_line = intersection[0]
        station_code = station_options[shared_line].keys()[0]
        destination_code = destination_options[shared_line].keys()[0]
        estimate = api_estimate(station_code, destination_code)
        return estimate

def api_estimate(station_code, destination_code):
    if station_code ==  destination_code:
        return "same_stations"
    headers = {'api_key': '0b6b7bdc525a4abc9d0ad9879bd5d17b',}
    params = urllib.urlencode({'FromStationCode': station_code, 'ToStationCode': destination_code,})
    try:
        conn = httplib.HTTPSConnection('api.wmata.com')
        conn.request("GET", "/Rail.svc/json/jSrcStationToDstStationInfo?{}".format(params), "{body}", headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        commute_time = data['StationToStationInfos'][0]['RailTime']
        return commute_time
    except:
        return "conn_problem"


def get_times(intent, session):
    card_title = intent['name']
    session_attributes = {}
    should_end_session = True
    try:
        station = intent['slots']['station']['value']
        station = get_equivalents(station)
        if len(intent['slots']['destination']) > 1:
            dest = intent['slots']['destination']['value']
            dest = get_equivalents(dest)
        else:
            dest = None
        if len(intent['slots']['line']) > 1:
            line = intent['slots']['line']['value']
            line = line.split()[0]  # if line is in the form "x line", set line to x
        else:
            line = None
        (times, station, destination) = query_station(station, dest, line)
        speech_output = get_speech_output(times, station, destination, line)
        reprompt_text = ""
    except KeyError:
        speech_output = ("Please specify your station of origin. For example, ask when is the next train "
                         "from Dupont circle to Shady Grove.")
        reprompt_text = "Get metro times by saying, for example, when is the next train from Dupont Circle."
    print(speech_output)
    return build_response(session_attributes, build_speechlet_response(
        card_title, speech_output, should_end_session, reprompt_text))


def query_station(station, destination, line):
    station_data = get_stations()
    station = name_lookup(station, station_data)
    if not station:
        return "invalid_station", station, destination
    st_options = get_options(station, station_data)
    if line:
        try:
            st_code = st_options[line].keys()[0]
        except KeyError:
            return "invalid_source_line", station, destination
    else:
        st_code = st_options[st_options.keys()[0]].keys()[0]
    times = retrieve_times(st_code, line)

    if destination is not None:
        destination = name_lookup(destination, station_data)
        if not destination:
            return "invalid_destination", station, destination
        if destination == station:
            return "same_stations", station, destination
        # Easter eggs
        if any(destination.lower() == x for x in ["dulles", "mordor"]):
            return destination

        # Find correct farragut
        if "farragut" in (station, destination):
            (station, destination) = which_farragut(station, destination, st_options, station_data)
            # recalculate station options
            st_options = get_options(station, station_data)

        dest_options = get_options(destination, station_data)
        if line:
            try:
                dest_code = dest_options[line].keys()[0]
            except KeyError:
                return "invalid_dest_line", station, destination
        intersection = [x for x in st_options.keys() if x in dest_options.keys()]

        if not intersection:
            times = "no_intersection"
        else:
            shared_line = intersection[0]
            st_code = st_options[shared_line].keys()[0]
            st_index = st_options[shared_line][st_code]
            dest_station = dest_options[shared_line].keys()[0]
            dest_index = dest_options[shared_line][dest_station]
            dest_trajectory = int(dest_index) - int(st_index)
            times = filter_times(times, intersection, station_data, st_index, dest_trajectory)

    return times, station, destination


def retrieve_times(st_code, line=None):
    headers = {'api_key': '0b6b7bdc525a4abc9d0ad9879bd5d17b',}
    params = urllib.urlencode({})
    try:
        conn = httplib.HTTPSConnection('api.wmata.com')
        conn.request("GET", "/StationPrediction.svc/json/GetPrediction/{}?{}".format(st_code, params), "{body}",
                     headers)
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
    except:
        return None
    if line:
        try:
            times = [(code2line(train[u'Line']), train[u'DestinationName'], train[u'Min']) for train in data[u'Trains']
                     if (line in code2line(train[u'Line']))]
        except KeyError:
            return "unknown_line"
    else:
        try:
            times = [(code2line(train[u'Line']), train[u'DestinationName'], train[u'Min']) for train in data[u'Trains']]
        except KeyError:
            return "unknown_line"
    return times


def filter_times(times, intersection, station_data, st_index, dest_trajectory):
    filtered_times = []
    for time in times:
        if not time[2]:
            continue
        for line in intersection:
            found = False
            for code in station_data[line]:
                if time[1].lower() == "train":
                    target_index = "a ghost station"
                    found = True
                    break
                if time[1].lower() in station_data[line][code]['Name'].lower():
                    target_index = station_data[line][code]['line_index']
                    found = True
                    break
            if found:
                if target_index == "a ghost station":
                    filtered_times.append(time)
                    break
                else:
                    targ_trajectory = int(target_index) - int(st_index)
                    if (targ_trajectory <= dest_trajectory < 0) or (0 < dest_trajectory <= targ_trajectory):
                        filtered_times.append(time)
    return filtered_times


# ======================================================================================================================
# Auxiliary and minor Functions
# ======================================================================================================================
def which_farragut(station, destination, st_options, station_data):
    if "farragut" in destination:
        if "red" in st_options.keys():
            destination = "farragut north"
        elif any(x in st_options.keys() for x in ["blue", "orange", "silver"]):
            destination = "farragut west"
    dest_options = get_options(destination, station_data)
    if "farragut" in station:
        if "red" in dest_options.keys():
            station = "farragut north"
        elif any(x in dest_options.keys() for x in ["blue", "orange", "silver"]):
            station = "farragut west"
    return station, destination


def get_options(station, station_data):
    st_options = {}
    for line in station_data:
        for code in station_data[line]:
            if station.lower() in station_data[line][code]['Name'].lower():
                st_code = code
                st_index = station_data[line][code]['line_index']
                st_line = line
                st_options[st_line] = {st_code: st_index}
    return st_options


def get_stations():
    with open("stations.json", "rb") as f:
        station_data = json.loads(f.read())
    return station_data


def name_lookup(station, station_data):
    name = ""
    for line in station_data:
        for code in station_data[line]:
            if station.lower() in station_data[line][code]['Name'].lower():
                name = station_data[line][code]['Name'].lower()
    return name


def code2line(line, reverse=False):
    line_codes = {"RD": "red line",
                  "BL": "blue line",
                  "OR": "orange line",
                  "SV": "silver line",
                  "YL": "yellow line",
                  "GR": "green line",
                  "--": "ghost train",
                  "": "ghost train",
                  "Train": "ghost train",
                  "No": "no passenger train"}
    if (not reverse) and (line in line_codes.keys()):
        code = line_codes[line]
        return code
    elif reverse:
        code = None
        for key, value in line_codes.iteritems():
            if line in value:
                code = key
                break
    else:
        code = None
    return code


def get_equivalents(station):
    if any(name in station.lower() for name in ["gallery", "china"]):
        station = "gallery"
    if "king st" in station.lower():
        station = "old town"
    if "vernon" in station.lower():
        station = "vernon"
    if "willy" in station.lower():
        station = "wiehle-reston east"
    if ("stadium" or "armory") in station.lower():
        station = "stadium-armory"
    if any(name in station.lower() for name in ["franconia", "springfield"]):
        station = "franconia-springfield"
    if any(name in station.lower() for name in ["african", "you street"]):
        station = "U street"
    if "maryland" in station.lower():
        station = "college park"
    if any(name in station.lower() for name in ["navy yard", "baseball", "nats park"]):
        station = "navy yard"
    if "howard" in station.lower():
        station = "howard"
    if "prince" in station.lower():
        station = "prince"
    if any(name in station.lower() for name in ["university of virginia", "virginia tech"]):
        station = "west falls church"
    if "american university" in station.lower():
        station = "tenleytown"
    if "grosvenor" in station.lower():
        station = "grosvenor"
    if "catholic" in station.lower():
        station = "brookland"
    if "gallaudet" in station.lower():
        station = "noma"
    if "georgia ave" in station.lower():
        station = "petworth"
    if "minnesota" in station.lower():
        station = "minnesota"
    if "potomac" in station.lower():
        station = "potomac"
    if "branch" in station.lower():
        station = "branch"
    if "rhode" in station.lower():
        station = "rhode island"
    if "zoo" in station.lower():
        station = "zoo"
    if "verizon" in station.lower():
        station = "gallery place"
    if "national mall" in station.lower():
        station = "smithsonian"
    if "dallas" in station.lower():
        station = "dulles"
    if any(station.lower() == x for x in ["know my", "number", "know muh", "no my", "know much"]):
        station = "noma"
    return station


def format_time(times):
    response = ""
    times = [(time[0], time[1], time[2]) for time in times if time[2] not in ("BRD", "ARR")]
    for i, time in enumerate(times):
        line = time[0]
        station = time[1]
        minutes = time[2]

        # replace weird station artifacts with intelligible names
        if station.lower() == "train":
            station = "a ghost station"
        if station.lower() == "no passenger":
            station = "an undisclosed station"

        # handle blank minutes field
        if not minutes:
            minutes = "unknown"

        # add 'and' before the last train in the list
        if len(times) != 1 and len(times) - i == 1:
            response += "and "

        # add proper indef articles to speech response
        if line == "orange line":
            response += "an "
        else:
            response += "a "

        # singularize 'minutes' if minutes = 1
        if minutes == "1":
            response += "{} to {} in {} minute, ".format(line, station, minutes)
        else:
            response += "{} to {} in {} minutes, ".format(line, station, minutes)

    # remove comma from end of line and replace with period.
    if response:
        stringt = response[:-1]
        stringt += "."

    return response


def get_speech_output(flag, station, destination, line=None):
    if flag is None:
        speech_output = "I'm having trouble reaching the Metro Transit website. Please try again in a few minutes."
    elif line == "line":
        speech_output = "sorry, I don't recognize that line."
    elif flag == "unknown_station":
        speech_output = "The Metro transit website is unresponsive. Please try again in a few minutes."
    elif flag == "invalid_destination":
        speech_output = "Sorry, I don't recognize that destination."
    elif flag == "invalid_station":
        speech_output = "Sorry, I don't recognize that station."
    elif flag == "invalid_source_line":
        speech_output = "Sorry, {} does not service {} line trains.".format(station, line)
    elif flag == "invalid_dest_line":
        speech_output = "Sorry, {} does not service {} line trains.".format(destination, line)
    elif flag == "no_intersection":
        speech_output = "Those stations don't connect."
    elif flag in ("mordor", "Mordor"):
        speech_output = "One does not simply metro to Mordor."
    elif flag in ("dulles", "Dulles"):
        speech_output = "One does not simply metro to dulles."
    elif flag == "conn_problem":
        speech_output = "I'm having trouble accessing the Metro transit website. Please try again in a few minutes."
    elif flag == "same_stations":
        speech_output = "Those are the same stations you silly goose!"
    elif isinstance(flag, int):
        if flag == 1:
            speech_output = "The current travel time between {} and {} is {} minute.".format(station, destination, flag)
        else:
            speech_output ="The current travel time between {} and {} is {} minutes.".format(station, destination, flag)
    else:
        str_time = format_time(flag)
        if str_time:
            speech_output = "there is {}".format(str_time)
        else:
            if line:
                if "line" not in line:
                    line += " line"
                if destination:
                    speech_output = "There are currently no {} trains scheduled from {} to {}.".format(line, station,
                                                                                                   destination)
                else:
                    speech_output = "There are currently no {} trains scheduled for {}.".format(line, station)
            else:
                if destination:
                    speech_output = "There are currently no trains scheduled from {} to {}.".format(station,
                                                                                                   destination)
                else:
                    speech_output = "There are currently no trains scheduled for {}.".format(station)

    return speech_output


# ======================================================================================================================
# helpers
# ======================================================================================================================
def build_speechlet_response(title, output, should_end_session, reprompt_text=""):
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': 'SessionSpeechlet - ' + title,
            'content': 'SessionSpeechlet - ' + output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session
    }


def build_response(session_attributes, speechlet_response):
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }


# ======================================================================================================================
# Run if invoked
# ======================================================================================================================
if __name__ == "__main__":
    with open("test_event.json", "rb") as f:
        event = json.loads(f.read())
    lambda_handler(event)