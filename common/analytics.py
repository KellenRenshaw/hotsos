#!/usr/bin/python3
import os

import statistics

from datetime import datetime


class LogSequenceCollection(object):
    """This class is used by the LogSequenceBase class to identify and
    collect log seqeunces defined by a start and end point.

    Sequences can span multiple files and are identified by an "event_id" which
    itself does not have to be unique and as such event_ids are tracked using
    unique identifiers.
    """
    def __init__(self):
        """Get stats on the collected sequences. We refer to sequences as
        samples in the results."""
        self._sequences = {}
        self.sequence_end_unique_ids = {}
        self.sequence_start_unique_ids = {}

    def has_complete_sequences(self):
        for s in self._sequences:
            if "start" in self._sequences[s]:
                return True

        return False

    @property
    def complete_sequences(self):
        sequences = {}
        for s in self._sequences:
            if "start" in self._sequences[s]:
                sequences[s] = self._sequences[s]

        return sequences

    def update_sequence(self, unique_key, key, value):
        self._sequences[unique_key][key] = value

    def add_sequence_end(self, key, end, duration=None):
        if key in self.sequence_end_unique_ids:
            self.sequence_end_unique_ids[key] += 1
        else:
            self.sequence_end_unique_ids[key] = 0

        seq_key = self.sequence_end_unique_ids[key]
        unique_sequence_key = "{}_{}".format(seq_key, key)

        self._sequences[unique_sequence_key] = {"end": end}
        if duration:
            self._sequences[unique_sequence_key]["duration"] = duration

        return unique_sequence_key

    def add_sequence_start(self, key, data):
        if key not in self.sequence_end_unique_ids:
            # cant add start for non-existant ending
            return

        # get new start id
        seq_key = self.sequence_start_unique_ids.get(key, -1)
        if seq_key >= 0:
            seq_key += 1
        else:
            seq_key = 0

        unique_sequence_key = "{}_{}".format(seq_key, key)

        # We only add start if end already found. If this is not the case it
        # could be an interrupted sequence or EOF.
        if unique_sequence_key not in self._sequences:
            return

        self.sequence_start_unique_ids[key] = seq_key
        self._sequences[unique_sequence_key]["start"] = data
        return unique_sequence_key

    def get_sequence(self, unique_key):
        return self._sequences[unique_key]


class SearchResultIndices(object):
    def __init__(self, day_idx=1, secs_idx=2, event_id_idx=3,
                 duration_idx=None):
        """
        This is used to know where to find required information within a
        SearchResult. The indexes refer to python.re groups.

        The minimum required information that a result must contain is day,
        secs and event_id. Results will be referred to using whatever event_id
        is set to. If the results contain a field for length of time between
        start and end this can be provided with duration_idx.
        """
        self.day = day_idx
        self.secs = secs_idx
        self.event_id = event_id_idx
        self.duration = duration_idx


class LogSequenceBase(object):
    """This base class is used to identify sequences within logs whereby a
    sequence has a start and end point. It can thenbe implemented by other
    classes to perform further analysis on sequence data.
    """

    def __init__(self, results, results_tag_prefix, log_seq_idxs=None):
        """
        @param results: FileSearcher results. This will be searched using
                        <results_tag_prefix>-start and <results_tag_prefix>-end
        @param results_tag_prefix: prefix of tag used for search results for
                                   sequences start and end.
        @param log_seq_idxs: optionally provide customer SearchResultIndices.
        """
        self.data = LogSequenceCollection()
        self.results = results
        self.results_tag_prefix = results_tag_prefix
        if not log_seq_idxs:
            log_seq_idxs = SearchResultIndices()

        self.log_seq_idxs = log_seq_idxs

    def get_sequences(self):
        end_tag = "{}-end".format(self.results_tag_prefix)
        for result in self.results.find_by_tag(end_tag):
            day = result.get(self.log_seq_idxs.day)
            secs = result.get(self.log_seq_idxs.secs)
            event_id = result.get(self.log_seq_idxs.event_id)
            duration = result.get(self.log_seq_idxs.duration)
            if duration is not None:
                duration = float(duration)

            end = "{} {}".format(day, secs)
            end = datetime.strptime(end, "%Y-%m-%d %H:%M:%S.%f")

            # event_id may have many updates over time across many files so we
            # need to have a way to make them unique.
            key = "{}_{}".format(os.path.basename(result.source), event_id)
            unique_key = self.data.add_sequence_end(key, end, duration)

        start_tag = "{}-start".format(self.results_tag_prefix)
        for result in self.results.find_by_tag(start_tag):
            day = result.get(self.log_seq_idxs.day)
            secs = result.get(self.log_seq_idxs.secs)
            event_id = result.get(self.log_seq_idxs.event_id)
            start = "{} {}".format(day, secs)
            start = datetime.strptime(start, "%Y-%m-%d %H:%M:%S.%f")

            key = "{}_{}".format(os.path.basename(result.source), event_id)
            unique_key = self.data.add_sequence_start(key, start)
            if unique_key:
                sequence = self.data.get_sequence(unique_key)
                if not sequence:
                    continue

                duration = sequence.get("duration")
                if duration is None:
                    end = sequence.get("end", None)
                    etime = end - start
                    if etime.total_seconds() < 0:
                        # this is probably a broken or invalid sequence so we
                        # set ingore it.
                        continue

                    duration = float(etime.total_seconds())

                self.data.update_sequence(unique_key, "duration", duration)

        if not self.data.has_complete_sequences():
            return

    def __call__(self):
        self.get_sequences()


class LogSequenceStats(LogSequenceBase):
    """ This class provides statistical information on log sequences."""

    def get_top_sequences(self, max, sort_by_key, reverse=False):
        count = 0
        top_n = {}
        top_n_sorted = {}

        valid_sequences = {}
        for k, v in self.data.complete_sequences.items():
            if v.get(sort_by_key):
                valid_sequences[k] = v

        for k, v in sorted(valid_sequences.items(),
                           key=lambda x: x[1].get(sort_by_key, 0),
                           reverse=reverse):
            # skip unterminated entries (e.g. on file wraparound)
            if "start" not in v:
                continue

            if count >= max:
                break

            count += 1
            top_n[k] = v

        for k, v in sorted(top_n.items(), key=lambda x: x[1]["start"],
                           reverse=reverse):
            event_id = k.rpartition('_')[2]
            event_id = event_id.partition('_')[0]
            top_n_sorted[event_id] = {"start": v["start"],
                                      "end": v["end"]}
            if v.get("duration"):
                top_n_sorted[event_id]["duration"] = v["duration"]

        return top_n_sorted

    def get_top_n_sorted(self, max):
        return self.get_top_sequences(max, sort_by_key="duration",
                                      reverse=True)

    def get_stats(self, key):
        sequences = self.data.complete_sequences.values()
        # ignore sequences with a duration None since they are invalid
        sequences = [s.get(key) for s in sequences if s.get(key) is not None]
        stats = {'min': round(min(sequences), 2),
                 'max': round(max(sequences), 2),
                 'stdev': round(statistics.pstdev(sequences), 2),
                 'avg': round(statistics.mean(sequences), 2),
                 'samples': len(sequences)}
        return stats
