const {
  eventTemplatesTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_event_templates',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Event Templates Collection');
    const result = await db.listCollections({ name: eventTemplatesTable }).toArray();

    if (result.length) {
      if (!resetDB) {
        console.log('Event Templates Collection already exists... running migrations.');

        // Migration: remove any null event_option_visibility fields (field should be absent, not null)
        try {
          const migrationResult = await db.collection(eventTemplatesTable).updateMany(
            { event_options: { $elemMatch: { event_option_visibility: null } } },
            { $unset: { 'event_options.$[elem].event_option_visibility': '' } },
            { arrayFilters: [{ 'elem.event_option_visibility': null }] }
          );
          if (migrationResult.modifiedCount > 0) {
            console.log(`Migrated ${migrationResult.modifiedCount} event template(s): removed null event_option_visibility fields.`);
          }

          // migrationResult = await db.collection(eventTemplatesTable).updateMany(
          //   { $rename: { 'is_power_logger': 'admin_only' } }
          // );
          // if (migrationResult.modifiedCount > 0) {
          //   console.log(`Migrated ${migrationResult.modifiedCount} event template(s): updated field names.`);
          // }
        }
        catch (err) {
          console.error('MIGRATION ERROR:', err);
          throw err;
        }

        console.log('Event Templates Collection migrations complete.');
        return;
      }

      console.log('Event Templates Collection exists... dropping it!');
      try {
        await db.dropCollection(eventTemplatesTable);
      }
      catch (err) {
        console.error('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Event Templates Collection');
    try {
      const collection = await db.createCollection(eventTemplatesTable);

      if (resetDB) {
        console.log('Populating Event Templates Collection');
        let init_data = [];

        if (process.env.SEALOG_INSTANCE_TYPE === 'Sub') {
          init_data = filePreProcessor('./init_data/system_templates_Sub.json', 'event_templates');
        }
        else if (process.env.SEALOG_INSTANCE_TYPE === 'emp') {
          init_data = filePreProcessor('./init_data/system_templates_emp.json', 'event_templates');
        }
        else {
          init_data = filePreProcessor('./init_data/system_templates_FKt.json', 'event_templates');
        }

        await collection.insertMany(init_data);
      }
    }
    catch (err) {
      console.error('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
