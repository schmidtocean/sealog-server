const {
  eventAuxDataTable
} = require('../config/db_constants');

const { filePreProcessor } = require('../lib/utils');

exports.plugin = {
  name: 'db_populate_event_aux_data',
  dependencies: ['hapi-mongodb'],
  register: async (server, options) => {

    const db = server.mongo.db;
    const resetDB = ['development', 'test'].includes(process.env.NODE_ENV);

    console.log('Searching for Event Aux Data Collection');
    const result = await db.listCollections({ name: eventAuxDataTable }).toArray();

    if (result.length) {
      if (!resetDB) {
        console.log('Event Aux Data Collection already exists... we\'re done here.');
        return;
      }

      console.log('Event Aux Data Collection exists... dropping it!');
      try {
        await db.dropCollection(eventAuxDataTable);
      }
      catch (err) {
        console.log('DROP ERROR:', err.code);
        throw (err);
      }
    }

    console.log('Creating Event Aux Data Collection');
    try {
      const collection = await db.createCollection(eventAuxDataTable);

      console.log('Creating index based on event_id field');
      await collection.createIndex({ event_id: 1 });

      if (resetDB) {
        console.log('Populating Event Aux Data Collection');

        let init_data = [];
        if (process.env.SEALOG_INSTANCE_TYPE === 'FKt') {
          init_data = filePreProcessor('./demo/FKt230303_auxDataExport.json', 'event_aux_data');
        }
        else if (process.env.SEALOG_INSTANCE_TYPE === 'Sub') {
          init_data = filePreProcessor('./demo/FKt230303_S0492_auxDataExport.json', 'event_aux_data');
        }
        else if (process.env.SEALOG_INSTANCE_TYPE === 'emp') {
          init_data = filePreProcessor('./demo/FKt260806_E0018_auxDataExport.json', 'event_aux_data');
        }

        if (init_data.length > 0) {
          await collection.insertMany(init_data);
        }
      }
    }
    catch (err) {
      console.log('CREATE ERROR:', err.code);
      throw (err);
    }
  }
};
