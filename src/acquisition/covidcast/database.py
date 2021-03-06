"""A utility class that handles database operations related to covidcast.

See src/ddl/covidcast.sql for an explanation of each field.
"""

# third party
import mysql.connector

# first party
import delphi.operations.secrets as secrets


class Database:
  """A collection of covidcast database operations."""

  DATABASE_NAME = 'epidata'

  def connect(self, connector_impl=mysql.connector):
    """Establish a connection to the database."""

    u, p = secrets.db.epi
    self._connection = connector_impl.connect(
        host=secrets.db.host,
        user=u,
        password=p,
        database=Database.DATABASE_NAME)
    self._cursor = self._connection.cursor()

  def disconnect(self, commit):
    """Close the database connection.

    commit: if true, commit changes, otherwise rollback
    """

    self._cursor.close()
    if commit:
      self._connection.commit()
    self._connection.close()

  def count_all_rows(self):
    """Return the total number of rows in table `covidcast`."""

    self._cursor.execute('SELECT count(1) FROM `covidcast`')

    for (num,) in self._cursor:
      return num

  def insert_or_update(
      self,
      source,
      signal,
      time_type,
      geo_type,
      time_value,
      geo_value,
      value,
      stderr,
      sample_size):
    """
    Insert a new row, or update an existing row, in the `covidcast` table.

    This has the intentional side effect of updating the primary timestamp.
    """

    sql = '''
      INSERT INTO `covidcast` VALUES
        (0, %s, %s, %s, %s, %s, %s, UNIX_TIMESTAMP(NOW()), %s, %s, %s, 0, NULL)
      ON DUPLICATE KEY UPDATE
        `timestamp1` = VALUES(`timestamp1`),
        `value` = VALUES(`value`),
        `stderr` = VALUES(`stderr`),
        `sample_size` = VALUES(`sample_size`)
    '''

    args = (
      source,
      signal,
      time_type,
      geo_type,
      time_value,
      geo_value,
      value,
      stderr,
      sample_size,
    )

    self._cursor.execute(sql, args)

  def get_data_stdev_across_locations(self):
    """
    Return the standard deviation of the data over all locations, for all
    (source, signal, geo_type) tuples.
    """

    sql = '''
      SELECT
        `source`,
        `signal`,
        `geo_type`,
        COALESCE(STD(`value`), 0) AS `aggregate_stdev`
      FROM
        `covidcast`
      WHERE
        `time_type` = 'day'
      GROUP BY
        `source`,
        `signal`,
        `geo_type`
    '''

    self._cursor.execute(sql)
    return list(self._cursor)

  def get_rows_with_stale_direction(self):
    """Return rows in the `covidcast` table where `direction` is stale.

    Note that this is limited to `time_type` of 'day' as direction is not yet
    defined at other time scales.

    To avoid runaway resource usage, the result set is limited to 10,000 rows.
    Rows are intentionally returned in random order promote update equity among
    the various data sources and geographic locations.
    """

    sql = '''
      SELECT
        c.`source`,
        c.`signal`,
        c.`time_type`,
        c.`geo_type`,
        c.`time_value`,
        c.`geo_value`,
        c.`timestamp2`,
        MAX(d.`timestamp1`) AS `max_timestamp1`,
        count(1) AS `support`
      FROM
        `covidcast` c JOIN `covidcast` d
      USING
        (`source`, `signal`, `time_type`, `geo_type`, `geo_value`)
      WHERE
        c.`time_type` = 'day' AND
        DATEDIFF(c.`time_value`, d.`time_value`) BETWEEN 0 AND 6
      GROUP BY
        c.`source`,
        c.`signal`,
        c.`time_type`,
        c.`geo_type`,
        c.`time_value`,
        c.`geo_value`
      HAVING
        MAX(d.`timestamp1`) > c.`timestamp2`
      ORDER BY
        rand()
      LIMIT
        10000
    '''

    self._cursor.execute(sql)
    return list(self._cursor)

  def get_rows_to_compute_direction(
      self,
      source,
      signal,
      geo_type,
      time_value,
      geo_value):
    """Return `covidcast` rows which can be used to compute `direction`."""

    sql = '''
      SELECT
        DATEDIFF(`time_value`, %s) AS `time_offset`,
        `value`
      FROM
        `covidcast`
      WHERE
        `source` = %s AND
        `signal` = %s AND
        `time_type` = 'day' AND
        `geo_type` = %s AND
        `geo_value` = %s AND
        DATEDIFF(`time_value`, %s) BETWEEN -6 and 0
      ORDER BY
        `time_value` ASC
    '''

    args = (
      time_value,
      source,
      signal,
      geo_type,
      geo_value,
      time_value,
    )

    self._cursor.execute(sql, args)
    return list(self._cursor)

  def update_direction(
      self,
      source,
      signal,
      time_type,
      geo_type,
      time_value,
      geo_value,
      direction):
    """
    Update the `direction` column for a given row in the `covidcast` table.

    This has the intentional side effect of updating the secondary timestamp.
    """

    sql = '''
      UPDATE
        `covidcast`
      SET
        `timestamp2` = UNIX_TIMESTAMP(NOW()),
        `direction` = %s
      WHERE
        `source` = %s AND
        `signal` = %s AND
        `time_type` = %s AND
        `geo_type` = %s AND
        `time_value` = %s AND
        `geo_value` = %s
    '''

    args = (
      direction,
      source,
      signal,
      time_type,
      geo_type,
      time_value,
      geo_value,
    )

    self._cursor.execute(sql, args)

  def get_keys_with_potentially_stale_direction(self):
    """
    Return the `covidcast` table composite key for each unique time-series for
    which all `direction` values can not be guaranteed to be fresh.

    Note that this is limited to `time_type` of 'day' as direction is not yet
    defined at other time scales.
    """

    sql = '''
      SELECT
        `source`,
        `signal`,
        `geo_type`,
        `geo_value`,
        MAX(`timestamp1`) AS `max_timestamp1`,
        MIN(`timestamp2`) AS `min_timestamp2`,
        MIN(`time_value`) AS `min_day`,
        MAX(`time_value`) AS `max_day`,
        COUNT(1) AS `series_length`
      FROM
        `covidcast`
      WHERE
        `time_type` = 'day'
      GROUP BY
        `source`,
        `signal`,
        `time_type`,
        `geo_type`,
        `geo_value`
      HAVING
        MAX(`timestamp1`) > MIN(`timestamp2`)
    '''

    self._cursor.execute(sql)
    return list(self._cursor)

  def get_daily_timeseries_for_direction_update(
      self, source, signal, geo_type, geo_value, min_day, max_day):
    """Return the indicated `covidcast` time-series, including timestamps."""

    sql = '''
      SELECT
        DATEDIFF(`time_value`, %s) AS `offset`,
        `time_value` AS `day`,
        `value`,
        `timestamp1`,
        `timestamp2`
      FROM
        `covidcast`
      WHERE
        `source` = %s AND
        `signal` = %s AND
        `time_type` = 'day' AND
        `geo_type` = %s AND
        `geo_value` = %s AND
        `time_value` BETWEEN %s AND %s
      ORDER BY
        `time_value` ASC
    '''

    args = (
      min_day,
      source,
      signal,
      geo_type,
      geo_value,
      min_day,
      max_day,
    )

    self._cursor.execute(sql, args)
    return list(self._cursor)

  def update_timeseries_timestamp2(
      self, source, signal, time_type, geo_type, geo_value):
    """Update the `timestamp2` column for an entire time-series.

    For daily time-series, this implies that all `direction` values in the
    specified time-series are confirmed fresh as of the current time. Even if
    they happened to be computed at an earlier time, this update indicates that
    those values are still fresh.

    This has no meaningful implication for non-daily time-series.
    """

    sql = '''
      UPDATE
        `covidcast`
      SET
        `timestamp2` = UNIX_TIMESTAMP(NOW())
      WHERE
        `source` = %s AND
        `signal` = %s AND
        `time_type` = %s AND
        `geo_type` = %s AND
        `geo_value` = %s
    '''

    args = (
      source,
      signal,
      time_type,
      geo_type,
      geo_value,
    )

    self._cursor.execute(sql, args)

  def update_covidcast_meta_cache(self, epidata_json):
    """Updates the `covidcast_meta_cache` table."""

    sql = '''
      UPDATE
        `covidcast_meta_cache`
      SET
        `timestamp` = UNIX_TIMESTAMP(NOW()),
        `epidata` = %s
    '''

    self._cursor.execute(sql, (epidata_json,))
